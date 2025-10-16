import pandas as pd
from flask import Flask, render_template, request, jsonify
import re
import math
from itertools import combinations
import numpy as np

app = Flask(__name__)

# --- Configuration & Global Variables ---
STUDENTS_CSV_PATH = 'students1.csv'
TIMETABLE_CSV_PATH = 'timetable1.csv'
LUNCH_SLOT = '12:30-01:30'
AVAILABLE_ROOMS = [f"NC{i:02d}" for i in range(1, 15)]
students_df_global, timetable_df_global, room_occupancy = None, None, {}
all_possible_slots, SUBJECT_OPTIONS, DIVISION_OPTIONS, DAYS_OPTIONS, TIMES_OPTIONS = [], [], [], [], []
student_schedule_map = {}

def load_and_prepare_data():
    global students_df_global, timetable_df_global, room_occupancy, all_possible_slots, SUBJECT_OPTIONS, DIVISION_OPTIONS, DAYS_OPTIONS, TIMES_OPTIONS, student_schedule_map
    try:
        students_df = pd.read_csv(STUDENTS_CSV_PATH, encoding='latin1', dtype={'MIS': str})
        timetable_df = pd.read_csv(TIMETABLE_CSV_PATH, encoding='latin1')

        for df in [students_df, timetable_df]:
            for col in df.select_dtypes(include=['object']).columns:
                df[col] = df[col].str.replace(r'\s+', ' ', regex=True).str.strip()

        name_cols = ['FirstName', 'MiddleName', 'LastName']
        for col in name_cols: students_df[col] = students_df[col].fillna('')
        students_df['Name'] = students_df[name_cols].apply(lambda x: ' '.join(x), axis=1).str.strip()
        students_df.drop(columns=name_cols, inplace=True)
        
        students_df_global = students_df.copy()
        
        unwanted_subjects_for_dropdown = ["LAB", "-CS- Communication Skills"]
        filtered_student_df = students_df_global[~students_df_global['Subject'].str.contains('|'.join(unwanted_subjects_for_dropdown), case=False, na=False)]
        SUBJECT_OPTIONS = sorted(filtered_student_df['Subject'].unique().tolist())
        DIVISION_OPTIONS = sorted(filtered_student_df['Division'].unique().tolist())
        
        timetable_df_global = timetable_df[timetable_df['Day'].str.lower() != 'saturday']
        timetable_df_global = timetable_df_global[timetable_df_global['Time'] != LUNCH_SLOT].copy()
        
        DAYS_OPTIONS = sorted(timetable_df_global['Day'].unique().tolist())
        TIMES_OPTIONS = sorted(timetable_df_global['Time'].unique().tolist())
        all_possible_slots = timetable_df_global[['Day', 'Time']].drop_duplicates().to_records(index=False).tolist()

        for slot in all_possible_slots:
            busy_rooms = set(timetable_df_global[(timetable_df_global['Day'] == slot[0]) & (timetable_df_global['Time'] == slot[1])]['Room'])
            room_occupancy[slot] = [room for room in AVAILABLE_ROOMS if room not in busy_rooms]

        all_students_mis = students_df_global['MIS'].unique()
        for mis in all_students_mis: student_schedule_map[mis] = set()
        enrollments = pd.merge(students_df_global, timetable_df_global, on=['Subject', 'Division'], how='inner')
        for _, row in enrollments.iterrows():
            student_schedule_map[row['MIS']].add((row['Day'], row['Time']))
        
        print("✅ Final definitive build loaded (Balanced, Fast, Top 3).")

    except Exception as e: print(f"FATAL ERROR: {e}")

load_and_prepare_data()

# --- ## UPGRADE: The function now finds the TOP solutions, not just one ## ---
def find_top_balanced_solutions(students_to_schedule, num_batches, availability_map):
    all_solutions = []
    
    # Limit combinations for performance if there are too many slots
    slot_keys = list(availability_map.keys())
    if len(slot_keys) > 50 and num_batches > 2: # Heuristic limit
        slot_combinations = [slot_keys[i:i+num_batches] for i in range(0, len(slot_keys), num_batches)]
    else:
        slot_combinations = combinations(slot_keys, num_batches)
    
    for slot_combination in slot_combinations:
        batches = [[] for _ in range(num_batches)]
        student_options = {}

        for student in students_to_schedule:
            possible_slots = [i for i, slot in enumerate(slot_combination) if student in availability_map[slot]['free_students']]
            if possible_slots:
                student_options[student] = possible_slots
        
        # Simple balanced assignment
        for student, options in student_options.items():
            smallest_batch_index = min(options, key=lambda i: len(batches[i]))
            batches[smallest_batch_index].append(student)
            
        unscheduled = students_to_schedule - set(s for b in batches for s in b)
        
        if not unscheduled: # Only consider perfect solutions that schedule everyone
            score = np.std([len(b) for b in batches]) # Lower is more balanced
            
            solution_details = []
            for i, batch in enumerate(batches):
                slot = slot_combination[i]
                solution_details.append({
                    'day': slot[0], 'time': slot[1],
                    'students': students_df_global[students_df_global['MIS'].isin(batch)].drop_duplicates(subset=['MIS']).to_dict('records'),
                    'available_rooms': availability_map[slot]['available_rooms']
                })
            
            all_solutions.append({'score': score, 'solution': solution_details})

    # Sort by balance score and return the top 3
    all_solutions.sort(key=lambda x: x['score'])
    return [s['solution'] for s in all_solutions[:3]]

@app.route('/check_availability', methods=['POST'])
def check_availability():
    # ... (This function is complete and correct)
    selected_day, selected_time = request.form.get('day'), request.form.get('time')
    target_mis_set = {mis for mis in re.split(r'[\s,]+', request.form.get('mis_numbers', '').strip()) if mis}
    if not all([selected_day, selected_time, target_mis_set]): return jsonify({'error': 'All fields are required.'}), 400
    busy_mis_set, free_mis_set = set(), set()
    slot_to_check = (selected_day, selected_time)
    for mis in target_mis_set:
        if slot_to_check in student_schedule_map.get(mis, set()): busy_mis_set.add(mis)
        else: free_mis_set.add(mis)
    busy_students_details, free_students_details = [], []
    if busy_mis_set:
        busy_enrollments = students_df_global[students_df_global['MIS'].isin(busy_mis_set)]
        busy_schedule = timetable_df_global[(timetable_df_global['Day'] == selected_day) & (timetable_df_global['Time'] == selected_time)]
        busy_details_df = pd.merge(busy_enrollments, busy_schedule, on=['Subject', 'Division'])
        busy_students_details = busy_details_df[['MIS', 'Name', 'Branch', 'Subject', 'Division', 'Room']].to_dict('records')
    if free_mis_set:
        free_students_df = students_df_global[students_df_global['MIS'].isin(free_mis_set)].drop_duplicates(subset=['MIS'])
        free_students_details = free_students_df[['MIS', 'Name', 'Branch']].to_dict('records')
    return jsonify({'free_results': free_students_details, 'busy_results': busy_students_details})

@app.route('/find_best_slots', methods=['POST'])
def find_best_slots():
    if not student_schedule_map: return jsonify({'error': 'Server data not loaded.'}), 500
    
    mode, requested_batches = request.form.get('mode'), int(request.form.get('num_batches', 1))
    if mode == 'by_group':
        subject, division = request.form.get('subject'), request.form.get('division')
        target_mis_set = set(students_df_global[(students_df_global['Subject'] == subject) & (students_df_global['Division'] == division)]['MIS'].unique())
    else:
        target_mis_set = {mis for mis in re.split(r'[\s,]+', request.form.get('mis_numbers', '').strip()) if mis}

    if not target_mis_set: return jsonify({'error': 'No students found.'}), 400

    availability_map = {}
    for slot in all_possible_slots:
        free_rooms = room_occupancy.get(slot, [])
        if not free_rooms: continue
        free_students_in_slot = {mis for mis in target_mis_set if slot not in student_schedule_map.get(mis, set())}
        if free_students_in_slot:
            availability_map[slot] = {'free_students': free_students_in_slot, 'available_rooms': free_rooms}
    
    # Try to fulfill the user's request
    top_solutions = find_top_balanced_solutions(target_mis_set, requested_batches, availability_map)

    if top_solutions:
        return jsonify({'status': 'success', 'solutions': top_solutions})
    
    # If request failed, find the true minimum number of batches required for a suggestion
    for i in range(requested_batches + 1, 5): # Limit suggestion search for performance
        suggestion_solutions = find_top_balanced_solutions(target_mis_set, i, availability_map)
        if suggestion_solutions:
            return jsonify({
                'status': 'failure_with_suggestion',
                'requested_batches': requested_batches,
                'suggestion': {'solutions': suggestion_solutions}
            })

    return jsonify({'status': 'failure_no_solution', 'requested_batches': requested_batches})

@app.route('/')
def index():
    return render_template('index.html', days=DAYS_OPTIONS, times=TIMES_OPTIONS, subjects=SUBJECT_OPTIONS, divisions=DIVISION_OPTIONS)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)