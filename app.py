import pandas as pd
from flask import Flask, render_template, request, jsonify
import re

app = Flask(__name__)

# --- Configuration ---
STUDENTS_CSV_PATH = 'students1.csv'
TIMETABLE_CSV_PATH = 'timetable1.csv'

# --- Pre-load and clean data ---
try:
    students_df = pd.read_csv(STUDENTS_CSV_PATH, encoding='latin1')
    timetable_df = pd.read_csv(TIMETABLE_CSV_PATH, encoding='latin1')

    # Clean and normalize all whitespace in text columns
    for col in students_df.select_dtypes(include=['object']).columns:
        students_df[col] = students_df[col].str.strip().str.replace(r'\s+', ' ', regex=True)
    
    for col in timetable_df.select_dtypes(include=['object']).columns:
        timetable_df[col] = timetable_df[col].str.strip().str.replace(r'\s+', ' ', regex=True)

    # Get dropdown options once
    DAYS_OPTIONS = sorted(timetable_df['Day'].unique().tolist())
    TIMES_OPTIONS = sorted(timetable_df['Time'].unique().tolist())

except FileNotFoundError as e:
    print(f"FATAL ERROR: Could not load data files on startup: {e}")
    students_df = None
    timetable_df = None

# --- Flask Routes ---

@app.route('/')
def index():
    """Renders the main page with dropdown options."""
    return render_template('index.html', days=DAYS_OPTIONS, times=TIMES_OPTIONS)

@app.route('/check_availability', methods=['POST'])
def check_availability():
    """Handles the background request from JavaScript and returns JSON data."""
    if students_df is None or timetable_df is None:
        return jsonify({'error': 'Server data not loaded correctly.'}), 500

    # Get User Input
    selected_day = request.form.get('day')
    selected_time = request.form.get('time')
    
    print("\n--- NEW REQUEST ---")
    print(f"Checking for Day: '{selected_day}' and Time: '{selected_time}'")

    # --- Core Logic ---
    busy_schedule = timetable_df[
        (timetable_df['Day'] == selected_day) & 
        (timetable_df['Time'] == selected_time)
    ]
    
    if busy_schedule.empty:
        print("DEBUG: FAILED to find any schedule entry in timetable1.csv for this Day/Time.")
    
    busy_mis_set = set()
    target_mis_list = re.split(r'[\s,]+', request.form.get('mis_numbers', '').strip())
    target_mis_set = set(map(str, [mis for mis in target_mis_list if mis]))
    
    if not busy_schedule.empty:
        for index, row in busy_schedule.iterrows():
            busy_subject = row['Subject']
            busy_division = row['Division']
            
            # This is the crucial debug print. The > < markers will reveal hidden spaces.
            print(f"DEBUG: Found a class. Now searching for Subject: >{busy_subject}< and Division: >{busy_division}< in students1.csv")
            
            all_busy_students = students_df[
                (students_df['Subject'] == busy_subject) & 
                (students_df['Division'] == busy_division)
            ]
            
            if all_busy_students.empty:
                print("DEBUG: FAILED to find any students for this Subject/Division combination.")
            else:
                print(f"DEBUG: SUCCESS! Found {len(all_busy_students)} student entries for this class.")
            
            all_busy_mis_set = set(map(str, all_busy_students['MIS'].unique()))
            busy_in_this_class = target_mis_set.intersection(all_busy_mis_set)
            busy_mis_set.update(busy_in_this_class)

    free_mis_set = target_mis_set - busy_mis_set
    # ... rest of the code is the same
    
    free_students_details = []
    if free_mis_set:
        result_df = students_df[students_df['MIS'].astype(str).isin(free_mis_set)].drop_duplicates(subset=['MIS'])
        for _, row in result_df.iterrows():
            free_students_details.append({
                'MIS': row['MIS'],
                'Name': f"{row['FirstName']} {row['LastName']}",
                'Branch': row['Branch']
            })

    return jsonify({'results': free_students_details})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)