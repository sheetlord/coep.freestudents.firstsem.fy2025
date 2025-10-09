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
    """Handles the background request and returns JSON with free and busy lists."""
    if students_df is None or timetable_df is None:
        return jsonify({'error': 'Server data not loaded correctly.'}), 500

    # Get User Input
    selected_day = request.form.get('day')
    selected_time = request.form.get('time')
    mis_input_text = request.form.get('mis_numbers', '')

    target_mis_list = re.split(r'[\s,]+', mis_input_text.strip())
    target_mis_list = [mis for mis in target_mis_list if mis]
    target_mis_set = set(map(str, target_mis_list))

    if not all([selected_day, selected_time, target_mis_list]):
        return jsonify({'error': 'All fields are required.'}), 400

    # --- Core Logic ---
    busy_schedule = timetable_df[
        (timetable_df['Day'] == selected_day) & 
        (timetable_df['Time'] == selected_time)
    ]
    
    busy_mis_set = set()
    busy_students_details = []
    
    if not busy_schedule.empty:
        for index, row in busy_schedule.iterrows():
            busy_subject = row['Subject']
            busy_division = row['Division']
            busy_room = row['Room']
            
            all_busy_students_in_class = students_df[
                (students_df['Subject'] == busy_subject) & 
                (students_df['Division'] == busy_division)
            ]
            
            all_busy_mis_in_class_set = set(map(str, all_busy_students_in_class['MIS'].unique()))
            
            # Find which of OUR target students are in this specific busy class
            busy_in_this_class_set = target_mis_set.intersection(all_busy_mis_in_class_set)
            
            if busy_in_this_class_set:
                # Add these students to the overall busy set
                busy_mis_set.update(busy_in_this_class_set)
                
                # Get details for the busy students in this class
                busy_details_df = students_df[students_df['MIS'].astype(str).isin(busy_in_this_class_set)].drop_duplicates(subset=['MIS'])
                for _, student_row in busy_details_df.iterrows():
                    busy_students_details.append({
                        'MIS': student_row['MIS'],
                        'Name': f"{student_row['FirstName']} {student_row['LastName']}",
                        'Branch': student_row['Branch'],
                        'Subject': busy_subject,
                        'Division': busy_division,
                        'Room': busy_room
                    })

    # Calculate free students
    free_mis_set = target_mis_set - busy_mis_set
    
    free_students_details = []
    if free_mis_set:
        result_df = students_df[students_df['MIS'].astype(str).isin(free_mis_set)].drop_duplicates(subset=['MIS'])
        for _, row in result_df.iterrows():
            free_students_details.append({
                'MIS': row['MIS'],
                'Name': f"{row['FirstName']} {row['LastName']}",
                'Branch': row['Branch']
            })

    return jsonify({'free_results': free_students_details, 'busy_results': busy_students_details})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)