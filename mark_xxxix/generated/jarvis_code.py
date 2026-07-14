import os
import shutil
import time
import random
import logging
import sys
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict

# --- Configuration for logging ---
# Set up logging to output to stderr, which keeps stdout clean for the task display.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

# --- Constants for display formatting ---
PROGRESS_BAR_FILLED_CHAR = '█'  # Unicode character for a filled block
PROGRESS_BAR_EMPTY_CHAR = '-'    # Character for empty part of the progress bar
PROGRESS_BAR_LENGTH = 10         # Number of characters for the progress bar itself (excluding brackets)
COLUMN_SEPARATOR = ' | '         # Separator string between columns in the display

# --- Task Status Enum ---
class TaskStatus(Enum):
    """Enumeration for the possible states of a task."""
    PENDING = "Pending"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

# --- Task Data Structure ---
@dataclass
class Task:
    """
    Represents a single task with its attributes.
    Using a dataclass provides a clean way to define data objects.
    """
    id: str
    description: str
    status: TaskStatus
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    progress: float = 0.0  # Normalized progress from 0.0 to 1.0

# --- Simulated Project Agent ---
class ProjectAgentSimulator:
    """
    A simulated `project_agent` that manages and updates tasks.
    In a real-world scenario, this would interface with a backend system
    (e.g., a database, an API, or a message queue) to get actual task data.
    """
    def __init__(self):
        """Initializes the simulator with an empty task list."""
        self._tasks: Dict[str, Task] = {}  # Stores tasks by their ID
        self._next_task_id = 1             # Counter for generating unique task IDs

    def create_task(self, description: str) -> Task:
        """
        Creates a new task with a given description and adds it to the agent's management.
        Returns the newly created Task object.
        """
        task_id = f"task_{self._next_task_id:03d}"  # e.g., "task_001"
        self._next_task_id += 1
        new_task = Task(id=task_id, description=description, status=TaskStatus.PENDING)
        self._tasks[task_id] = new_task
        logging.info(f"Created new task: {task_id} - {description}")
        return new_task

    def _simulate_task_progress(self, task: Task) -> None:
        """
        Internal helper method to randomly update a task's status and progress
        for simulation purposes.
        """
        if task.status == TaskStatus.PENDING:
            # Randomly start a pending task
            if random.random() < 0.2: # 20% chance to start
                task.status = TaskStatus.RUNNING
                task.start_time = datetime.now()
                task.progress = 0.05 # Initial progress
                logging.debug(f"Task {task.id} started.")
        elif task.status == TaskStatus.RUNNING:
            # Increment progress if still running
            if task.progress < 0.95:
                task.progress += random.uniform(0.05, 0.2) # Increment by 5-20%
                task.progress = min(task.progress, 1.0) # Cap progress at 1.0
            else:
                # Decide whether to complete or fail when nearly done
                if random.random() < 0.8: # 80% chance to complete
                    task.status = TaskStatus.COMPLETED
                    logging.info(f"Task {task.id} completed.")
                else: # 20% chance to fail
                    task.status = TaskStatus.FAILED
                    logging.warning(f"Task {task.id} failed.")
                task.end_time = datetime.now()
                task.progress = 1.0 # Ensure progress is 1.0 at completion/failure
        # For COMPLETED, FAILED, CANCELLED tasks, no further simulation updates.

    def get_all_tasks(self) -> List[Task]:
        """
        Retrieves all managed tasks. In this simulation, it also triggers
        the internal progress simulation for each task before returning.
        In a real system, this would fetch the current state from the backend.
        """
        for task in self._tasks.values():
            self._simulate_task_progress(task) # Update task states for simulation
        # Return a copy to prevent external modification of the internal dictionary
        return sorted(list(self._tasks.values()), key=lambda t: t.id)

# --- Display Utilities ---
def clear_console() -> None:
    """
    Clears the terminal screen. Works on both Windows ('cls') and Unix-like ('clear') systems.
    """
    os.system('cls' if os.name == 'nt' else 'clear')

def format_duration(start_time: Optional[datetime], end_time: Optional[datetime]) -> str:
    """
    Calculates and formats the duration between two datetime objects into HH:MM:SS.
    If end_time is None, it calculates duration up to the current time.
    """
    if not start_time:
        return "N/A" # No start time, cannot calculate duration

    actual_end_time = end_time if end_time else datetime.now()
    duration = actual_end_time - start_time
    total_seconds = int(duration.total_seconds())

    # Handle negative duration if end_time somehow precedes start_time
    if total_seconds < 0:
        return "N/A"

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def format_task_display(tasks: List[Task], terminal_width: int) -> List[str]:
    """
    Formats a list of Task objects into displayable strings, adapting column
    widths to fit the terminal width.
    """
    if not tasks:
        return ["No active tasks to display."]

    # Define column headers and their static/minimum widths
    headers = ["ID", "Description", "Status", "Progress", "Duration"]
    header_id_width = len("ID")
    header_description_width = len("Description")
    header_status_width = len("Status")
    header_progress_width = len("Progress") # Will be replaced by bar width
    header_duration_width = len("Duration")

    # Calculate actual content widths for each column based on data
    # Ensure minimum width is at least the header width
    id_col_width = max(header_id_width, max((len(task.id) for task in tasks), default=0))
    status_col_width = max(header_status_width, max((len(task.status.value) for task in tasks), default=0))
    duration_col_width = len("HH:MM:SS") # Fixed width for formatted duration string

    # Progress bar always has a fixed display width (e.g., [████------])
    progress_col_width = PROGRESS_BAR_LENGTH + 2 # +2 for the brackets

    # Calculate remaining width available for the 'Description' column
    # Account for separators between columns (3 chars for ' | ')
    num_separators = len(headers) - 1 # There are 4 separators for 5 columns
    fixed_columns_total_width = (
        id_col_width + status_col_width + progress_col_width + duration_col_width + (num_separators * len(COLUMN_SEPARATOR))
    )
    available_for_description = terminal_width - fixed_columns_total_width

    # Ensure description column width is reasonable:
    # - At least its header length
    # - Not less than a practical minimum (e.g., 20 characters)
    # - Not more than the largest description in content OR the available space.
    max_content_desc_len = max((len(task.description) for task in tasks), default=0)
    description_col_width = max(
        header_description_width,
        min(max_content_desc_len, available_for_description, 50) # Cap at 50 chars if too wide
    )
    # If terminal is very narrow, description might need to shrink further, to a minimum of 10.
    if description_col_width < 10 and available_for_description > 10:
        description_col_width = available_for_description

    # Final check for total width, if still exceeds terminal width, some truncation/wrapping might occur.
    # We will rely on f-string truncation for description.

    lines = []
    # Construct the header line
    header_line = (
        f"{'ID':<{id_col_width}}{COLUMN_SEPARATOR}"
        f"{'Description':<{description_col_width}}{COLUMN_SEPARATOR}"
        f"{'Status':<{status_col_width}}{COLUMN_SEPARATOR}"
        f"{'Progress':<{progress_col_width}}{COLUMN_SEPARATOR}"
        f"{'Duration':<{duration_col_width}}"
    )
    lines.append(header_line)
    lines.append("-" * len(header_line)) # Separator line for header

    # Format each task into a displayable string
    for task in tasks:
        # Truncate description if it's too long for the allocated width
        display_description = (
            (task.description[:description_col_width - 3] + '...')
            if len(task.description) > description_col_width and description_col_width > 3
            else task.description
        )

        # Create the progress bar string
        filled_length = int(PROGRESS_BAR_LENGTH * task.progress)
        bar = (
            PROGRESS_BAR_FILLED_CHAR * filled_length +
            PROGRESS_BAR_EMPTY_CHAR * (PROGRESS_BAR_LENGTH - filled_length)
        )
        progress_str = f"[{bar}]"

        # Format task duration
        duration_str = format_duration(task.start_time, task.end_time)

        # Construct the task's data line
        task_line = (
            f"{task.id:<{id_col_width}}{COLUMN_SEPARATOR}"
            f"{display_description:<{description_col_width}}{COLUMN_SEPARATOR}"
            f"{task.status.value:<{status_col_width}}{COLUMN_SEPARATOR}"
            f"{progress_str:<{progress_col_width}}{COLUMN_SEPARATOR}"
            f"{duration_str:<{duration_col_width}}"
        )
        lines.append(task_line)

    return lines

# --- Main Monitoring Function ---
def monitor_tasks(agent: ProjectAgentSimulator, refresh_interval_seconds: int = 2) -> None:
    """
    Continuously monitors and displays the status of tasks managed by the given agent.
    Refreshes the console output at the specified interval.

    Args:
        agent: An instance of ProjectAgentSimulator (or a compatible class) to fetch tasks from.
        refresh_interval_seconds: The time in seconds between display updates.
    """
    logging.info(f"Starting task monitor with refresh interval: {refresh_interval_seconds} seconds...")
    print("Initializing task monitor...")

    try:
        while True:
            clear_console()  # Clear previous output for a clean, refreshing display

            try:
                # Get current terminal width to adjust display formatting dynamically
                terminal_width = shutil.get_terminal_size().columns
                if terminal_width < 80: # Warn if terminal is too narrow
                    logging.warning(f"Terminal width ({terminal_width}) is very narrow. Display might be truncated.")

                # Fetch the latest list of tasks from the agent
                active_tasks = agent.get_all_tasks()

                # Format tasks into a list of strings for console display
                display_lines = format_task_display(active_tasks, terminal_width)

                # Print the formatted task information to the console
                for line in display_lines:
                    print(line)

                # Add a footer with last update time and instructions
                print(f"\nLast updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Refresh interval: {refresh_interval_seconds}s. Press Ctrl+C to stop.")

            except Exception as e:
                # Catch and log any errors that occur during the fetch/display cycle
                logging.error(f"Error encountered during task monitoring loop: {e}", exc_info=True)
                print(f"\nError: Could not display tasks. See log for details (stderr).")
                print(f"Retrying in {refresh_interval_seconds} seconds...")

            # Wait for the specified interval before refreshing again
            time.sleep(refresh_interval_seconds)

    except KeyboardInterrupt:
        # Handle user interruption (Ctrl+C) gracefully
        logging.info("Task monitoring stopped by user (KeyboardInterrupt).")
        print("\nTask monitoring stopped.")
    except Exception as e:
        # Catch any other unexpected critical errors that might break the monitoring loop
        logging.critical(f"An unexpected critical error occurred, stopping monitor: {e}", exc_info=True)
        print(f"\nCritical error: {e}")

# --- Main Execution Block ---
if __name__ == "__main__":
    # Create an instance of our simulated project agent
    project_agent = ProjectAgentSimulator()

    # Create some initial tasks to demonstrate the monitoring functionality
    # These tasks will simulate their progress over time
    project_agent.create_task("Initialize project repository and setup virtual environment")
    project_agent.create_task("Install core dependencies (Django, Flask, etc.)")
    project_agent.create_task("Configure database connections and migrations")
    project_agent.create_task("Develop authentication module for users")
    project_agent.create_task("Implement main API endpoints for data access")
    project_agent.create_task("Write comprehensive unit tests for backend logic")
    project_agent.create_task("Design and build frontend user interface components")
    project_agent.create_task("Deploy application to staging server for testing")
    project_agent.create_task("Run end-to-end integration tests")
    project_agent.create_task("Prepare project documentation and user guides")

    # Start monitoring the tasks managed by the project_agent
    # The refresh interval can be adjusted here
    monitor_tasks(project_agent, refresh_interval_seconds=1) # Refresh every 1 second