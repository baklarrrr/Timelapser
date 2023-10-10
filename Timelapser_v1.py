import cv2
import numpy as np
import pyautogui
import os
import time
from tkinter import messagebox, StringVar
from PIL import Image, ImageTk
import tkinter as tk
from PIL import ImageDraw
import threading
from screeninfo import get_monitors
from pynput import keyboard, mouse
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
import tkinter.simpledialog as simpledialog

video_process_future = None
check_video_process_scheduled = False

last_input_time = time.time()
input_lock = Lock()

shared_var_lock = threading.Lock()

mouse_pressed = False
initial_mouse_x, initial_mouse_y = 0, 0
current_mouse_x, current_mouse_y = 0, 0


roi_update_active = True
timelapse_active = False
bottom_controls_frame = None

global timelapse_running
timelapse_running = False

last_mouse_movement_time = time.time()

last_updated_roi = None

shared_var_lock = threading.Lock()

#callback functions to update the last input time when a mouse or keyboard event is detected
def on_key_event(key):
    global last_input_time
    with input_lock:
        print("Keyboard input detected!")  # Debug line
        last_input_time = time.time()

def on_mouse_event(x, y, button, pressed):
    global last_input_time
    with input_lock:
        # Check for button being None to account for mouse movement
        # And mouse movement will not have any button attribute
        if pressed or button is None:
            print("Mouse activity detected!")  # Debug line
            last_input_time = time.time()

def on_mouse_move(x, y):
    global last_input_time, last_mouse_movement_time
    current_time = time.time()
    if current_time - last_mouse_movement_time >= 0.5:  # 0.1 seconds = 100ms
        with input_lock:
            print("Mouse movement detected!")  # Debug line
            last_input_time = current_time
            last_mouse_movement_time = current_time



keyboard_listener = keyboard.Listener(on_press=on_key_event)
keyboard_listener.start()
mouse_listener = mouse.Listener(on_click=on_mouse_event, on_move=on_mouse_move)
mouse_listener.start()

# Hide the console window
#import ctypes
#ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

sequence_number = 0

# Create a new image with a transparent background
folder_icon = Image.new('RGBA', (32, 32), (0, 0, 0, 0))

# Get a drawing context for the image
draw = ImageDraw.Draw(folder_icon)

# Draw a rectangle for the folder shape
draw.rectangle([(4, 4), (28, 24)], outline='black', width=2)

# Draw a triangle at the bottom of the rectangle
draw.polygon([(8, 24), (16, 28), (24, 24)], fill='black')

# Save the image to a file
folder_icon.save('folder_icon.png')


class OverlayROIWindow(tk.Toplevel):
    def __init__(self, master, callback, *args, **kwargs):
        super().__init__(master, *args, **kwargs)

        self.callback = callback
        self.attributes("-alpha", 0.8)
        self.configure(bg="gray50")
        self.overrideredirect(True)

        # Define the active area on the selected monitor
        x, y, w, h = ACTIVE_AREA

        # Set the window size and position to match the active area on the selected monitor
        self.geometry(f"{w}x{h}+{x}+{y}")

        self.canvas = tk.Canvas(self, bg="gray50", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.bind("<Button-1>", self.on_mouse_click)
        self.bind("<B1-Motion>", self.on_mouse_move)
        self.bind("<ButtonRelease-1>", self.on_mouse_release)

    def on_mouse_click(self, event):
        self.initial_mouse_x = event.x
        self.initial_mouse_y = event.y

    def on_mouse_move(self, event):
        x1, y1 = self.initial_mouse_x, self.initial_mouse_y
        x2, y2 = event.x, event.y

        self.canvas.delete("roi")
        self.canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=3, tags="roi")

    def on_mouse_release(self, event):
        roi_x = min(self.initial_mouse_x, event.x)
        roi_y = min(self.initial_mouse_y, event.y)
        roi_w = abs(self.initial_mouse_x - event.x)
        roi_h = abs(self.initial_mouse_y - event.y)

        self.callback(roi_x, roi_y, roi_w, roi_h)

class SimpleTooltip:
    def __init__(self, widget, text, delay=500):  # Added delay parameter (default is 500ms)
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.id = None
        self.x = self.y = 0
        self.delay = delay
        self.widget.bind("<Enter>", self.schedule)
        self.widget.bind("<Leave>", self.hidetip)
        self.widget.bind("<Button-1>", self.hidetip)  # Hide tooltip on click

    def schedule(self, event=None):
        self.id = self.widget.after(self.delay, self.showtip)  # Schedule showing tooltip after delay

    def showtip(self, event=None):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None

        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(1)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, background="#ffffe0", relief="solid", borderwidth=1)
        label.pack()

    def hidetip(self, event=None):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None
        tw = self.tooltip_window
        self.tooltip_window = None
        if tw:
            tw.destroy()


class DurationPlanner(tk.Toplevel):
    def __init__(self, master, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.title("Duration Planner")

        # Set the icon to be the same as the master
        self.iconbitmap(icon_file_path)
        
        self.label1 = tk.Label(self, text="Timelapse Length (minutes):")
        self.label1.pack(padx=10, pady=5)
        SimpleTooltip(self.label1, "How long you want the timelapse to be as a video.")
        
        self.timelapse_duration_entry = tk.Entry(self)
        self.timelapse_duration_entry.pack(padx=10, pady=5)
        
        self.label2 = tk.Label(self, text="Recording Length (minutes):")
        self.label2.pack(padx=10, pady=5)
        SimpleTooltip(self.label2, "How long you plan to film your timelapse recording.")
        
        self.real_time_duration_entry = tk.Entry(self)
        self.real_time_duration_entry.pack(padx=10, pady=5)
        
        self.label3 = tk.Label(self, text="Frame Speed (frames per second):")
        self.label3.pack(padx=10, pady=5)
        SimpleTooltip(self.label3, "How smooth you want the timelapse to be. Higher numbers make smoother videos.")
        
        self.fps_entry = tk.Entry(self)
        self.fps_entry.pack(padx=10, pady=5)
        
        self.calculate_button = tk.Button(self, text="Calculate", command=self.calculate)
        self.calculate_button.pack(padx=10, pady=20)

        self.update_idletasks()
        x, y = root.winfo_pointerxy()  # get the mouse cursor's position
        self.geometry(f"+{x}+{y}")  # set the window's position
    
    def calculate(self):
        try:
            timelapse_duration = int(float(self.timelapse_duration_entry.get())) * 60  # Convert to seconds
            real_time_duration = int(float(self.real_time_duration_entry.get())) * 60  # Convert to seconds
            fps = int(float(self.fps_entry.get()))
            
            interval = (real_time_duration / timelapse_duration) / fps
            
            # Update the main window entries
            interval_entry.delete(0, tk.END)
            interval_entry.insert(0, str(interval))
            
            duration_entry.delete(0, tk.END)
            duration_entry.insert(0, str(real_time_duration / 60))  # Convert back to minutes for consistency
            
            frame_rate_entry.delete(0, tk.END)
            frame_rate_entry.insert(0, str(fps))
            
            self.destroy()  # Close the dialog
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid numbers.")

def create_tooltip(widget, text):
    SimpleTooltip(widget, text)

def open_duration_planner():
    planner = DurationPlanner(root)
    planner.mainloop()

def select_roi():
    global ACTIVE_AREA  # Access the global ACTIVE_AREA variable
    monitor = get_monitors()[monitor_index]  # Get the selected monitor using the monitor_index

    # Set the new monitor as the active area to record and sample ROI from
    active_area = (monitor.x, monitor.y, monitor.width, monitor.height)

    # Lock the threading lock to ensure that the active area is set before continuing with the program
    with shared_var_lock:  # Use shared_var_lock instead of Lock()
        ACTIVE_AREA = active_area

    roi_window = tk.Toplevel(root)
    roi_window.attributes("-alpha", 0.3)
    roi_window.geometry(f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}")  # Set to the resolution and position of the selected monitor
    roi_window.attributes("-fullscreen", True)
    roi_window.attributes("-topmost", True)
    roi_window.bind("<Button-1>", on_roi_window_click)
    roi_window.bind("<B1-Motion>", on_roi_window_drag)
    roi_window.bind("<ButtonRelease-1>", on_roi_window_release)

    # Capture the screen and convert it to a PhotoImage
    screen = capture_screen()
    screen = Image.fromarray(screen)
    screen = ImageTk.PhotoImage(screen)

    # Create a canvas to draw the ROI rectangle
    canvas = tk.Canvas(roi_window, bg="white")
    canvas.pack(fill=tk.BOTH, expand=True)
    canvas.create_image(0, 0, image=screen, anchor=tk.NW)

    roi_window.mainloop()


def on_roi_window_click(event):
    global roi_start_x, roi_start_y
    roi_start_x, roi_start_y = event.x, event.y

def on_roi_window_drag(event):
    global roi_start_x, roi_start_y
    x, y = event.x, event.y
    event.widget.delete("roi_rectangle")
    event.widget.create_rectangle(roi_start_x, roi_start_y, x, y, outline="red", width=3, tags="roi_rectangle")


def on_roi_window_release(event):
    global roi_start_x, roi_start_y
    roi_end_x, roi_end_y = event.x, event.y
    roi_coords = (roi_start_x, roi_start_y, abs(roi_end_x - roi_start_x), abs(roi_end_y - roi_start_y))

    # Update the ROI entry with the new coordinates
    roi_entry.delete(0, tk.END)
    roi_entry.insert(0, ','.join(map(str, roi_coords)))

    event.widget.master.destroy()



def open_roi_overlay():
    overlay_window = OverlayROIWindow(root)
    overlay_window.mainloop()

def generate_video(output_folder, video_name, frame_rate):
    images = [img for img in os.listdir(output_folder) if img.endswith(".png")]
    if not images:  # check if the images list is empty
        print("No images found in the directory.")
        return
    images.sort()  # ensure images are processed in the correct order
    frame = cv2.imread(os.path.join(output_folder, images[0]))
    h, w, layers = frame.shape
    video = cv2.VideoWriter(video_name, cv2.VideoWriter_fourcc(*'mp4v'), frame_rate, (w,h))

    for image in images:
        video.write(cv2.imread(os.path.join(output_folder, image)))

    cv2.destroyAllWindows()
    video.release()


def capture_screen():
    screen = pyautogui.screenshot(region=ACTIVE_AREA)
    return cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)


def update_preview(roi_coords):
    if not roi_update_active:
        return

    x, y, w, h = roi_coords
    screen = capture_screen()
    outlined_screen = draw_roi_rectangle(screen, x, y, w, h)

    # Resize the image to fit the application's window size
    window_width = image_label.winfo_width()
    window_height = image_label.winfo_height()
    max_size = (window_width, window_height)
    resized_image = resize_image(outlined_screen, max_size)

    tk_image = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(resized_image, cv2.COLOR_BGR2RGB)))
    image_label.config(image=tk_image)
    image_label.image = tk_image

def calculate_timelapse_info():
    try:
        interval = int(float(interval_entry.get()))  # seconds
        duration = int(float(duration_entry.get())) * 60  # convert minutes to seconds
        fps = int(frame_rate_entry.get())
    except ValueError:
        messagebox.showerror("Invalid Input", "Please enter valid numbers for interval, duration, and FPS.")
        return
    
    total_frames = duration / interval
    timelapse_duration = total_frames / fps  # seconds

    # Assuming an average file size per frame, say 2MB
    # This value could be refined based on actual data
    avg_file_size_per_frame = 2  # MB
    estimated_file_size = total_frames * avg_file_size_per_frame  # MB
    
    timelapse_speed = interval * fps  # This represents how many real-time seconds are condensed into one second of timelapse
    
    # Convert durations from seconds to a more readable format
    real_time_duration_str = f"{duration // 3600} hours, {(duration % 3600) // 60} minutes"
    timelapse_duration_str = f"{timelapse_duration // 60} minutes, {timelapse_duration % 60:.2f} seconds"
    
    info_text = (
        f"Total Frames: {total_frames}\n"
        f"Estimated File Size: {estimated_file_size} MB\n"
        f"Timelapse Speed: 1 second of timelapse equals {timelapse_speed} seconds of real time\n"
        f"Real-Time Duration: {real_time_duration_str}\n"
        f"Timelapse Duration: {timelapse_duration_str}"
    )
    
    simpledialog.messagebox.showinfo("Timelapse Information", info_text)

def convert_preview_to_screenshot_coords(x, y, max_size):
    screen = capture_screen()
    screen_width, screen_height = screen.shape[1], screen.shape[0]
    preview_width, preview_height = max_size

    factor_x = screen_width / preview_width
    factor_y = screen_height / preview_height

    return int(x * factor_x), int(y * factor_y)

# Initialize the monitor index to 0
monitor_index = 0

# Define the active area as the entire screen of the primary monitor
monitors = get_monitors()
ACTIVE_AREA = (monitors[0].x, monitors[0].y, monitors[0].width, monitors[0].height)


def switch_monitor():
    global monitor_index
    monitors = get_monitors()
    monitor_index = (monitor_index + 1) % len(monitors)
    selected_monitor = monitors[monitor_index]

    # Move the application window to the center of the selected monitor
    root.geometry("+%d+%d" % (selected_monitor.x + (selected_monitor.width - root.winfo_width()) // 2,
                              selected_monitor.y + (selected_monitor.height - root.winfo_height()) // 2))

    # Update the button text
    monitor_button.config(text=f"Active Monitor: {selected_monitor.name}")

    # Set the new monitor as the active area to record and sample ROI from
    active_area = (selected_monitor.x, selected_monitor.y, selected_monitor.width, selected_monitor.height)

    # Lock the threading lock to ensure that the active area is set before continuing with the program
    with shared_var_lock:  # Use shared_var_lock instead of Lock()
        global ACTIVE_AREA
        ACTIVE_AREA = active_area

    # Set the default ROI to the full resolution of the selected monitor
    roi_entry.delete(0, tk.END)
    roi_entry.insert(0, f"{selected_monitor.x},{selected_monitor.y},{selected_monitor.width},{selected_monitor.height}")

    # Call the update_preview() function to update the preview manually
    try:
        roi_coords = tuple(map(int, roi_entry.get().split(",")))
        update_preview(roi_coords)
    except ValueError:
        pass







def save_image_with_quality(image, filepath, quality, label_width=15):
    if quality >= 100:
        # Save the image without compression
        cv2.imwrite(filepath, image)
    else:
        # Save the image with the specified JPEG quality
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        _, encoded_image = cv2.imencode('.jpg', image, encode_param)
        with open(filepath, 'wb') as f:
            f.write(encoded_image)

    # Update the quality_label text with the fixed width
    text = f"JPEG Quality (%): {quality}"
    quality_label['text'] = text.ljust(label_width)


def run_timelapse():
    # Code related to taking screenshots and saving them
    # This should be the main loop of your timelapse task
    pass  # Remove this line after adding your timelapse task code


def start_timelapse():
    global timelapse_running
    global sequence_number

    if not timelapse_running:
        timelapse_running = True
        start_button_text.set("Pause Timelapse")
        sequence_number = 0

        # Halt ROI updates and adjust the button
        global roi_update_active
        roi_update_active = False

        # Create output folder if it doesn't exist
        output_folder_path = os.path.join(os.getcwd(), "timelapse")
        if not os.path.exists(output_folder_path):
            os.makedirs(output_folder_path)

        interval = int(float(interval_entry.get()))
        duration = int(float(duration_entry.get())) * 60
        roi_coords = tuple(map(int, roi_entry.get().split(",")))

        start_time = time.time()
        root.after(int(interval * 1000), save_timelapse, start_time, output_folder_path, interval, duration, roi_coords)
    else:
        timelapse_running = False
        start_button_text.set("Start Timelapse")




def stop_timelapse():
    global timelapse_running
    global sequence_number
    global video_process_future  # global reference to the future object

    if timelapse_running:
        timelapse_running = False
        start_button_text.set("Start Timelapse")
        start_button.config(bg='#8ebf49')  # Reset the button color to the default
        messagebox.showinfo("Timelapse Stopped", f"Timelapse finished. {sequence_number} frames captured.")

        # Restart ROI updates and adjust the button
        global roi_update_active
        roi_update_active = True

    output_folder_path = os.path.join(os.getcwd(), "timelapse")
    video_name = os.path.join(output_folder_path, 'timelapse_video.mp4')
    frame_rate = int(float(frame_rate_entry.get()))  # Convert string to float, then float to int

    def process_video():
        with ThreadPoolExecutor() as executor:
            global video_process_future
            video_process_future = executor.submit(generate_video, output_folder_path, video_name, frame_rate)

    # Start the video processing in a separate thread
    video_processing_thread = threading.Thread(target=process_video)
    video_processing_thread.start()

    # Schedule the check_video_process function to run periodically
    check_video_process()

def check_video_process():
    global video_process_future
    global check_video_process_scheduled  # Access the global variable

    if video_process_future is None:
        # Video processing has not started yet
        if not check_video_process_scheduled:
            check_video_process_scheduled = True
            root.after(1000, check_video_process)  # check again in 1 second
    elif video_process_future.done():
        messagebox.showinfo("Video Processing Complete", "The video has been successfully processed.")
        video_process_future = None  # reset the future object
        check_video_process_scheduled = False  # Reset the flag
    else:
        # Video processing is still ongoing
        check_video_process_scheduled = True  # Set flag here to ensure rescheduling
        root.after(1000, check_video_process)  # check again in 1 second




drawing_roi = False
roi_start_x, roi_start_y = None, None

def define_roi(event, x, y, flags, param):
    global drawing_roi, roi_start_x, roi_start_y
    if event == cv2.EVENT_LBUTTONDOWN:
        drawing_roi = True
        roi_start_x, roi_start_y = x, y
    elif event == cv2.EVENT_MOUSEMOVE:
        if drawing_roi:
            roi_entry.delete(0, 'end')
            roi_entry.insert(0, f"{roi_start_x},{roi_start_y},{x - roi_start_x},{y - roi_start_y}")
            update_preview((roi_start_x, roi_start_y, x - roi_start_x, y - roi_start_y))
    elif event == cv2.EVENT_LBUTTONUP:
        drawing_roi = False
        roi_entry.delete(0, 'end')
        roi_entry.insert(0, f"{roi_start_x},{roi_start_y},{x - roi_start_x},{y - roi_start_y}")
        update_preview((roi_start_x, roi_start_y, x - roi_start_x, y - roi_start_y))



def get_roi_from_mouse_coordinates():
    x = min(initial_mouse_x, current_mouse_x)
    y = min(initial_mouse_y, current_mouse_y)
    w = abs(initial_mouse_x - current_mouse_x)
    h = abs(initial_mouse_y - current_mouse_y)
    return x, y, w, h



def update_roi_preview():
    try:
        roi_coords = tuple(map(int, roi_entry.get().split(",")))
        update_preview(roi_coords)
    except ValueError:
        messagebox.showerror("Invalid ROI", "Invalid ROI coordinates entered. Please enter valid coordinates in the format x,y,w,h.")

def draw_roi_rectangle(image, x, y, w, h, color=(255, 0, 0), thickness=10):
    img = Image.fromarray(image)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(x, y), (x+w, y+h)], outline=color, width=thickness)
    return np.array(img)

def resize_image(image, max_size):
    img = Image.fromarray(image)
    img.thumbnail(max_size, Image.LANCZOS)
    return np.array(img)


def update_preview_periodic():
    global last_updated_roi
    try:
        current_roi = tuple(map(int, roi_entry.get().split(",")))
        if roi_update_active and current_roi != last_updated_roi:
            update_preview(current_roi)
            last_updated_roi = current_roi
    except ValueError:
        pass
    root.after(100, update_preview_periodic)


def on_closing():
    global roi_update_active
    global sequence_number
    roi_update_active = False
    sequence_number = 0
    root.destroy()

def save_timelapse(start_time, path, interval, duration, roi_coords):
    global sequence_number
    x, y, w, h = roi_coords

    current_time = time.time()
    delay = int(float(input_detection_interval_entry.get()))

    with input_lock:
        time_since_last_input = current_time - last_input_time
        if time_since_last_input <= delay:
            screen = capture_screen()
            cropped_screen = screen[y:y+h, x:x+w]

            timestamp = int(time.time() - start_time)
            sequence_name = sequence_name_entry.get() or "timelapse_one"
            padding = int(frame_padding_spinbox.get())
            padding_format = f"{{:0{padding}d}}"

            if overwrite_files.get():
                filename = f"{sequence_name}_{padding_format.format(sequence_number)}.png"
            else:
                filename = f"{sequence_name}_{padding_format.format(sequence_number)}_{padding_format.format(timestamp)}.png"

            filepath = os.path.join(path, filename)
            quality = int(quality_slider.get())  # Get the selected quality value
            save_image_with_quality(cropped_screen, filepath, quality)  # Save the image with the specified quality

            sequence_number += 1  # Increment the sequence_number by 1 after saving an image

        # Schedule the next call to save_timelapse if the timelapse is still running, 
        # the timelapse_running flag is still True, and the duration has not been reached
        if time.time() - start_time < duration and timelapse_running:
            root.after(int(interval * 1000), save_timelapse, start_time, path, interval, duration, roi_coords)
        else:
            stop_timelapse()


def initial_roi_update():
    try:
        roi_coords = tuple(map(int, roi_entry.get().split(",")))
        update_preview(roi_coords)
    except ValueError:
        pass

def update_quality_label(val):
    val = int(val)
    if val <= 20:
        quality_text = "Minimal"
    elif val <= 40:
        quality_text = "Low"
    elif val <= 60:
        quality_text = "Medium"
    elif val <= 80:
        quality_text = "Good"
    elif val <= 99:
        quality_text = "Great"
    else:
        quality_text = "Uncompressed"
    quality_label.config(text=f"Quality: {quality_text}", bg='#F5F5F5')  # Add the bg attribute here as well.


def open_output_folder():
    folder_path = os.path.join(os.getcwd(), "timelapse")
    if os.path.exists(folder_path):
        os.startfile(folder_path)
    else:
        messagebox.showwarning("Output Folder Not Found", "The output folder does not exist yet. Please start a timelapse to generate images.")


def show_input_listener_delay_info(event):
    messagebox.showinfo("Input Listener Delay", "This is the interval in seconds for detecting mouse movements/inputs and keystrokes. If no input is detected during the specified interval, screenshots will be paused. Once input is detected again, the timelapse will resume.")



###################################################################

# Application Title

root = tk.Tk()
root.title("Timelapser")
root.configure(bg="#1a1a1a")
root.geometry("1400x700")

script_directory = os.path.dirname(os.path.realpath(__file__))
icon_file_path = os.path.join(script_directory, 'TL.ico')
root.iconbitmap(icon_file_path)

###################################################################


# Create a frame for the top controls
top_controls_frame = tk.Frame(root, bg='#454545', height=40)
top_controls_frame.pack(side=tk.TOP, pady=10, fill=tk.X)

start_button_text = StringVar()
start_button_text.set("Start Timelapse")

start_button = tk.Button(top_controls_frame, textvariable=start_button_text, command=start_timelapse, bg='#8ebf49')
start_button.pack(side=tk.LEFT, padx=10, anchor="center")

stop_button = tk.Button(top_controls_frame, text="Stop Recording", command=stop_timelapse, bg='#e74c3c')  # Red-colored stop button
stop_button.pack(side=tk.LEFT, padx=(0, 10), anchor="center")


input_detection_interval_label = tk.Label(top_controls_frame, text="Input Listener Delay (s):", bg='#6e5ab0')
input_detection_interval_label.pack(side=tk.LEFT, padx=(10, 0), anchor="w")

input_detection_interval_entry = tk.Entry(top_controls_frame, width=5)
input_detection_interval_entry.pack(side=tk.LEFT, anchor="w")
input_detection_interval_entry.insert(0, "30")

#question_mark_button = tk.Button(top_controls_frame, text="?", command=show_input_listener_delay_info, width=2, height=1)
#question_mark_button.pack(side=tk.LEFT, padx=(0, 10))

# Add a question mark label to show information about the input listener delay
question_mark_label = tk.Label(top_controls_frame, text="?", bg='#333333', fg='#E0E0E0', font=("Helvetica", 10, "bold"))
question_mark_label.bind("<Button-1>", show_input_listener_delay_info)
question_mark_label.pack(side=tk.LEFT, padx=(0, 10), anchor="center")

frame_rate_label = tk.Label(top_controls_frame, text="Frame Rate:")
frame_rate_label.pack(side=tk.LEFT, padx=5, pady=5)

frame_rate_entry = tk.Entry(top_controls_frame, width=5)
frame_rate_entry.pack(side=tk.LEFT, padx=5, pady=5)
frame_rate_entry.insert(0, "30")  # Default value of 30 fps







def update_quality_label(val):
    val = int(val)
    if val <= 20:
        quality_text = "Minimal"
    elif val <= 40:
        quality_text = "Low"
    elif val <= 60:
        quality_text = "Medium"
    elif val <= 80:
        quality_text = "Good"
    elif val <= 99:
        quality_text = "Great"
    else:
        quality_text = "Uncompressed"
    quality_text_label.config(text=f"Quality: {quality_text}", bg='#F5F5F5')

quality_label = tk.Label(top_controls_frame, text="JPEG Quality (%):", bg='#F5F5F5', width=20)
quality_label.pack(side=tk.LEFT, padx=(10, 0), anchor="w")

quality_slider = tk.Scale(top_controls_frame, from_=1, to=100, orient=tk.HORIZONTAL, command=update_quality_label, bg='#F5F5F5')
quality_slider.set(100)  # Default quality value
quality_slider.pack(side=tk.LEFT, padx=(0, 10), anchor="w")


quality_text_label = tk.Label(top_controls_frame, text="Quality: Uncompressed", bg='#F5F5F5')
quality_text_label.pack(side=tk.LEFT, anchor="w")



spacer_label = tk.Label(top_controls_frame, width=2, bg='#454545')
spacer_label.pack(side=tk.LEFT)

planner_button = tk.Button(top_controls_frame, text="Video Planner", command=open_duration_planner, bg='#eb5e92')
planner_button.pack(side=tk.LEFT, padx=(0, 10), anchor="center")


info_button = tk.Button(top_controls_frame, text="Calculate Info", command=calculate_timelapse_info)
info_button.pack(side=tk.LEFT, padx=(10, 0), anchor="w")

spacer_label = tk.Label(top_controls_frame, width=2, bg='#454545')
spacer_label.pack(side=tk.LEFT)

output_folder_button = tk.Button(top_controls_frame, text="Open Output Folder", command=open_output_folder)
output_folder_button.pack(side=tk.RIGHT, padx=(0, 10), anchor="center")

select_roi_button = tk.Button(top_controls_frame, text="Select ROI", command=select_roi, bg='#30A7A0')
select_roi_button.pack(side=tk.RIGHT, padx=(0, 10), anchor="center")


# Create a frame for settings
bottom_controls_frame = tk.Frame(root, bg='#454545')  # Replace '#F5F5F5' with any color you prefer.
bottom_controls_frame.pack(side=tk.BOTTOM, pady=10)

# Add a frame padding selector
frame_padding_label = tk.Label(bottom_controls_frame, text="Frame Padding:", bg='#F5F5F5')
frame_padding_label.pack(side=tk.LEFT, padx=(10, 0))

frame_padding_spinbox = tk.Spinbox(bottom_controls_frame, from_=4, to=8, width=3)
frame_padding_spinbox.pack(side=tk.LEFT, padx=(0, 10))
frame_padding_spinbox.delete(0, tk.END)  # Clear the default value
frame_padding_spinbox.insert(0, '5')  # Set the default frame padding value to 5

# Add a text box to allow the user to name the image sequence
sequence_name_label = tk.Label(bottom_controls_frame, text="Sequence Name:", bg='#F5F5F5')
sequence_name_label.pack(side=tk.LEFT, padx=(10, 0), anchor="w")

sequence_name_entry = tk.Entry(bottom_controls_frame)
sequence_name_entry.insert(0, "timelapse_one")
sequence_name_entry.pack(side=tk.LEFT, padx=(0, 10), anchor="w")

interval_label = tk.Label(bottom_controls_frame, text="Interval (s):")
interval_label.pack(side=tk.LEFT, anchor="w")

interval_entry = tk.Entry(bottom_controls_frame)
interval_entry.pack(side=tk.LEFT, anchor="w")
#set interval default
interval_entry.insert(0, "15")

duration_label = tk.Label(bottom_controls_frame, text="Duration (min):")
duration_label.pack(side=tk.LEFT, padx=(10, 0), anchor="w")

duration_entry = tk.Entry(bottom_controls_frame)
duration_entry.pack(side=tk.LEFT, anchor="w")
#set duration default
duration_entry.insert(0, "720")

roi_label = tk.Label(bottom_controls_frame, text="ROI (x,y,w,h):")
roi_label.pack(side=tk.LEFT, padx=(10, 0), anchor="w")

roi_entry = tk.Entry(bottom_controls_frame)
roi_entry.pack(side=tk.LEFT, padx=(10, 0), anchor="w")
#set ROI default
roi_entry.insert(0, "0,0,1920,1080")

#roi_preview_button = tk.Button(settings_frame, text="Update ROI Preview", command=update_roi_preview)
#roi_preview_button.pack(side=tk.LEFT, padx=(10, 0))

monitor_button = tk.Button(bottom_controls_frame, text="Monitor", command=switch_monitor)
monitor_button.pack(side=tk.LEFT, padx=(10, 0), anchor="w")

image_label = tk.Label(root, bg="#2b2b2b")
image_label.pack(fill=tk.BOTH, expand=True)

overwrite_files = tk.BooleanVar()
overwrite_files.set(True)

overwrite_checkbox = tk.Checkbutton(bottom_controls_frame, text="Overwrite Files", variable=overwrite_files, bg="#1b2b3b")
overwrite_checkbox.pack(side=tk.LEFT, padx=(10, 0), anchor="w")

# Add tooltips to widgets in the top_controls_frame

create_tooltip(start_button, "Start recording the timelapse.")
create_tooltip(stop_button, "Stop recording the timelapse.")
create_tooltip(input_detection_interval_label, "Input Listener Delay: Time in seconds to wait for a lack of user input before pausing the timelapse.")
create_tooltip(input_detection_interval_entry, "Enter the time in seconds to wait for user input.")
create_tooltip(frame_rate_label, "Frames Per Second (FPS): The number of frames shown in one second. Higher FPS gives smoother video.")
create_tooltip(frame_rate_entry, "Enter the Frames Per Second (FPS) for your timelapse video.")
create_tooltip(quality_label, "JPEG Quality: Lower values save space but reduce image quality.")
create_tooltip(quality_slider, "Slide to adjust the JPEG quality.")
create_tooltip(planner_button, "Open the Duration Planner.")
create_tooltip(info_button, "Calculate and display timelapse information.")
create_tooltip(select_roi_button, "Select a region of interest for the timelapse.")
create_tooltip(output_folder_button, "Open the folder containing timelapse outputs.")

# Add tooltips to widgets in the bottom_controls_frame
create_tooltip(frame_padding_label, "Frame Padding: Number of zeros to add to the frame count numbers.")
create_tooltip(frame_padding_spinbox, "Select the number of zeros to pad the frame count. E.g., 'timelapse_one_03' for a padding of 2.")
create_tooltip(sequence_name_label, "Sequence Name: Name of the image sequence.")
create_tooltip(sequence_name_entry, "Enter the name for your image sequence.")
create_tooltip(interval_label, "Interval: Time in seconds between frames.")
create_tooltip(interval_entry, "Enter the time interval between frames in seconds.")
create_tooltip(duration_label, "Duration: Total recording time in minutes.")
create_tooltip(duration_entry, "Enter the total recording duration in minutes.")
create_tooltip(roi_label, "ROI (x,y,w,h): Region of Interest coordinates.")
create_tooltip(roi_entry, "Enter the ROI coordinates as x,y,width,height.")
create_tooltip(monitor_button, "Switch monitor for recording.")
create_tooltip(overwrite_checkbox, "Overwrite existing files with the same name.")


update_quality_label(quality_slider.get())

update_preview_periodic()
root.protocol("WM_DELETE_WINDOW", on_closing)

root.after(30, initial_roi_update)  # Schedule the initial_roi_update function to run after 30ms

root.mainloop()