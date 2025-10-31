import pandas as pd
from flask import Flask, render_template, request, jsonify, send_file
import re
import math
from itertools import combinations, product
import numpy as np
import io  

app = Flask(__name__)

# --- Configuration & Global Variables ---
STUDENTS_CSV_PATH = 'students1.csv'
TIMETABLE_CSV_PATH = 'timetable1.csv'
LUNCH_SLOT = '12:30-01:30'
AVAILABLE_ROOMS = [f"NC{i:02d}" for i in range(1, 15)] # NC01 to NC14
MAX_BATCH_OPTIONS = 5
TOP_N_SOLUTIONS_TO_SHOW = 10
TOP_N_SLOTS_HEURISTIC = 30

students_df_global, timetable_clash_global, room_occupancy = None, None, {}
all_possible_slots, SUBJECT_OPTIONS, DIVISION_OPTIONS, DAYS_OPTIONS, TIMES_OPTIONS_FORMATTED, TIMES_OPTIONS_FULL, ALL_DAYS_OPTIONS = [], [], [], [], [], [], []
TIMES_OPTIONS_FORMATTED_END = []
student_schedule_map = {}
subject_division_map = {} 

def to_float_time(time_str):
    if not time_str: return 0
    try:
        start_time_str = time_str.split('-')[0].strip()
        parts = start_time_str.split(':')
        hour = int(parts[0])
        minute = int(parts[1])
        if hour < 8: hour += 12
        return hour + (minute / 60.0)
    except Exception: return 0

def load_and_prepare_data():
    """
    Loads all data, performs cleaning, and pre-computes schedules for maximum speed.
    """
    global students_df_global, timetable_clash_global, room_occupancy, all_possible_slots, SUBJECT_OPTIONS, DIVISION_OPTIONS, DAYS_OPTIONS, TIMES_OPTIONS_FORMATTED, TIMES_OPTIONS_FORMATTED_END, TIMES_OPTIONS_FULL, ALL_DAYS_OPTIONS, student_schedule_map, subject_division_map
    try:
        students_df = pd.read_csv(STUDENTS_CSV_PATH, encoding='latin1', dtype={'MIS': str})
        timetable_df = pd.read_csv(TIMETABLE_CSV_PATH, encoding='latin1')

        # 1. Aggressive Cleaning
        for df in [students_df, timetable_df]:
            for col in df.select_dtypes(include=['object']).columns:
                df[col] = df[col].str.replace(r'\s+', ' ', regex=True).str.strip()

        # 2. Create 'Name' Column
        name_cols = ['FirstName', 'MiddleName', 'LastName']
        for col in name_cols: students_df[col] = students_df[col].fillna('')
        students_df['Name'] = students_df[name_cols].apply(lambda x: ' '.join(x), axis=1).str.strip()
        students_df.drop(columns=name_cols, inplace=True)
        
        # 3. Store Unfiltered Student Data
        students_df_global = students_df.copy()
        
        # 4. Create Filtered Dropdown Lists
        unwanted_subjects_for_dropdown = ["LAB", "-CS- Communication Skills"]
        filtered_student_df = students_df_global[~students_df_global['Subject'].str.contains('|'.join(unwanted_subjects_for_dropdown), case=False, na=False)]
        SUBJECT_OPTIONS = sorted(filtered_student_df['Subject'].unique().tolist())
        DIVISION_OPTIONS = sorted(students_df_global['Division'].unique().tolist())
        
        # 5. Create the Subject-Division Map
        for subject in SUBJECT_OPTIONS:
            subject_divisions = students_df_global[students_df_global['Subject'] == subject]['Division'].unique()
            subject_division_map[subject] = sorted(list(subject_divisions))
        
        # 6. Create Full Timetable (for Mode 1 and Busy Map)
        timetable_clash_global = timetable_df.copy()
        ALL_DAYS_OPTIONS = sorted(timetable_clash_global['Day'].unique().tolist())
        DAYS_OPTIONS = sorted(timetable_clash_global['Day'].unique().tolist())

        # 7. Build Global Lookups
        # List 2: For Modes 1, 2 (Display & Value: "08:30 - 09:30")
        unique_times_full = timetable_clash_global['Time'].unique().tolist()
        TIMES_OPTIONS_FULL = sorted(unique_times_full, key=to_float_time)
        
        # 8. Build Performance Map (uses full timetable to know all busy slots)
        all_students_mis = students_df_global['MIS'].unique()
        for mis in all_students_mis: student_schedule_map[mis] = set()
        enrollments = pd.merge(students_df_global, timetable_clash_global, on=['Subject', 'Division'], how='inner')
        for _, row in enrollments.iterrows():
            student_schedule_map[row['MIS']].add((row['Day'], row['Time']))

        # 9. Create "Schedulable" data (FOR MODES 2-5) by removing lunch
        timetable_schedulable = timetable_clash_global[timetable_clash_global['Time'] != LUNCH_SLOT].copy()
        
        # 10. Build Schedulable-Only Lists (for Modes 2-5)
        # List 1: For "FROM" dropdowns (Modes 3, 4, 5) - NO LUNCH
        unique_times_schedulable = timetable_schedulable['Time'].unique().tolist()
        sorted_times_schedulable = sorted(unique_times_schedulable, key=to_float_time)
        TIMES_OPTIONS_FORMATTED = [(t.split('-')[0].strip(), t) for t in sorted_times_schedulable]
        
        # List 1.B: For "TO" dropdowns (Modes 3, 4, 5) - NO LUNCH
        TIMES_OPTIONS_FORMATTED_END = [(t.split('-')[1].strip(), t) for t in sorted_times_schedulable]
        
        # 11. Build Schedulable Slots Pool (FOR MODES 2-5)
        records_list = timetable_schedulable[['Day', 'Time']].drop_duplicates().to_records(index=False).tolist()
        all_possible_slots = sorted(list(set(records_list)), key=lambda x: (ALL_DAYS_OPTIONS.index(x[0]), to_float_time(x[1])))

        # Build room occupancy based on SCHEDULABLE slots only
        for slot in all_possible_slots:
            busy_rooms = set(timetable_schedulable[(timetable_schedulable['Day'] == slot[0]) & (timetable_schedulable['Time'] == slot[1])]['Room'])
            room_occupancy[slot] = [room for room in AVAILABLE_ROOMS if room not in busy_rooms]
        
        print(f"✅ Final {len(list(app.url_map.iter_rules()))}-Mode build loaded (Balanced, Fast, v5.18_FINAL).")

    except Exception as e: print(f"FATAL ERROR: {e}")

load_and_prepare_data()

# --- (All helper functions and all 5 Mode routes are 100% correct) ---
def _get_target_students(form_data):
    if form_data.get('student_mode') == 'by_group':
        subject, division = form_data.get('subject'), form_data.get('division')
        target_mis_set = set(students_df_global[(students_df_global['Subject'] == subject) & (students_df_global['Division'] == division)]['MIS'].unique())
    else: # by_mis
        target_mis_set = {mis for mis in re.split(r'[\s,]+', form_data.get('mis_numbers', '').strip()) if mis}
    return target_mis_set

def _get_student_availability_map(target_mis_set, slot_pool):
    availability_map = {}
    for slot in slot_pool:
        free_rooms = room_occupancy.get(slot, [])
        if not free_rooms: continue
        # This check works because student_schedule_map *includes* lunch
        free_students_in_slot = {mis for mis in target_mis_set if slot not in student_schedule_map.get(mis, set())}
        if free_students_in_slot:
            availability_map[slot] = {'free_students': free_students_in_slot, 'available_rooms': free_rooms}
    return availability_map

def _find_balanced_solutions(students_to_schedule, num_batches, availability_map):
    slot_keys = list(availability_map.keys())
    
    # Apply heuristic if pool is too large
    if len(slot_keys) > TOP_N_SLOTS_HEURISTIC and num_batches > 1:
        top_slots = sorted(availability_map.keys(), key=lambda s: len(availability_map[s]['free_students']), reverse=True)
        slot_keys = top_slots[:TOP_N_SLOTS_HEURISTIC]
        
    if len(slot_keys) < num_batches: return []

    solutions_diff_days = []
    solutions_same_day = [] 
    
    for slot_combination in combinations(slot_keys, num_batches):
        batches = [[] for _ in range(num_batches)]
        student_options = {}
        for student in students_to_schedule:
            possible_slots = [i for i, slot in enumerate(slot_combination) if student in availability_map[slot]['free_students']]
            if possible_slots: student_options[student] = possible_slots
        
        for student, options in sorted(student_options.items(), key=lambda item: len(item[1])):
            smallest_batch_index = min(options, key=lambda i: len(batches[i]))
            batches[smallest_batch_index].append(student)
            
        unscheduled = students_to_schedule - set(s for b in batches for s in b)
        
        if not unscheduled: 
            score = np.std([len(b) for b in batches]) 
            solution_details = []
            for i, batch in enumerate(batches):
                slot = slot_combination[i]
                solution_details.append({
                    'day': slot[0], 'time': slot[1],
                    'students': students_df_global[students_df_global['MIS'].isin(batch)].drop_duplicates(subset=['MIS']).to_dict('records'),
                    'available_rooms': availability_map[slot]['available_rooms']
                })
            
            days_in_combo = {slot[0] for slot in slot_combination}
            if len(days_in_combo) == num_batches:
                solutions_diff_days.append({'score': score, 'solution': solution_details})
            else:
                solutions_same_day.append({'score': score, 'solution': solution_details})

    solutions_diff_days.sort(key=lambda x: x['score'])
    solutions_same_day.sort(key=lambda x: x['score'])
    all_solutions = solutions_diff_days + solutions_same_day
    
    return [s['solution'] for s in all_solutions[:TOP_N_SOLUTIONS_TO_SHOW]]

def _parse_slot_filters(form_data, prefix=""):
    days = form_data.getlist(f'{prefix}days')
    time_start_str, time_end_str = form_data.get(f'{prefix}time_start'), form_data.get(f'{prefix}time_end')
    
    if not days or not time_start_str or not time_end_str: return [tuple(slot) for slot in all_possible_slots] 
    
    time_start, time_end = to_float_time(time_start_str), to_float_time(time_end_str)
    filtered_slots = []
    # This correctly checks against the "schedulable" slots
    for slot in all_possible_slots:
        day, time_str = slot
        if day in days:
            slot_time = to_float_time(time_str)
            if time_start <= slot_time <= time_end:
                filtered_slots.append(slot)
    return filtered_slots

@app.route('/check_availability', methods=['POST'])
def check_availability():
    selected_day, selected_time = request.form.get('day'), request.form.get('time')
    target_mis_set = {mis for mis in re.split(r'[\s,]+', request.form.get('mis_numbers', '').strip()) if mis}
    if not all([selected_day, selected_time, target_mis_set]): return jsonify({'error': 'All fields are required.'}), 400
    
    # This uses timetable_clash_global, which *includes* lunch, so it's correct.
    busy_schedule = timetable_clash_global[(timetable_clash_global['Day'] == selected_day) & (timetable_clash_global['Time'] == selected_time)]
    busy_mis_set, busy_students_details = set(), []
    for _, busy_class in busy_schedule.iterrows():
        students_in_class = students_df_global[(students_df_global['Subject'] == busy_class['Subject']) & (students_df_global['Division'] == busy_class['Division'])]
        conflicted_students = target_mis_set.intersection(set(students_in_class['MIS']))
        if conflicted_students:
            busy_mis_set.update(conflicted_students)
            busy_details = students_df_global[students_df_global['MIS'].isin(conflicted_students)].drop_duplicates(subset=['MIS'])
            for _, student in busy_details.iterrows():
                busy_students_details.append({'MIS': student['MIS'], 'Name': student['Name'], 'Branch': student['Branch'], 'Subject': busy_class['Subject'], 'Division': busy_class['Division'], 'Room': busy_class['Room']})
    free_mis_set = target_mis_set - busy_mis_set
    free_students_details = []
    if free_mis_set:
        result_df = students_df_global[students_df_global['MIS'].isin(free_mis_set)].drop_duplicates(subset=['MIS'])
        free_students_details = result_df[['MIS', 'Name', 'Branch']].to_dict('records')
    return jsonify({'free_results': free_students_details, 'busy_results': busy_students_details})

@app.route('/mode_2_batch_finder', methods=['POST'])
def mode_2_batch_finder():
    if not student_schedule_map: return jsonify({'error': 'Server data not loaded.'}), 500
    target_mis_set = _get_target_students(request.form)
    requested_batches = int(request.form.get('num_batches', 1))
    if not target_mis_set: return jsonify({'error': 'No students found.'}), 400
    excluded_slot_strings = request.form.getlist('excluded_slots')
    excluded_slots = {tuple(s.split('|')) for s in excluded_slot_strings}
    
    # This uses all_possible_slots, which *excludes* lunch, so it's correct.
    allowed_slot_pool = [slot for slot in all_possible_slots if slot not in excluded_slots]
    availability_map = _get_student_availability_map(target_mis_set, allowed_slot_pool)
    solutions = _find_balanced_solutions(target_mis_set, requested_batches, availability_map)
    if solutions:
        return jsonify({'status': 'success', 'solutions': solutions})
    for i in range(requested_batches + 1, MAX_BATCH_OPTIONS + 1):
        suggestion_solutions = _find_balanced_solutions(target_mis_set, i, availability_map)
        if suggestion_solutions:
            return jsonify({'status': 'failure_with_suggestion', 'requested_batches': requested_batches, 'suggestion': {'solutions': suggestion_solutions}})
    return jsonify({'status': 'failure_no_solution', 'requested_batches': requested_batches})

@app.route('/mode_3_advanced_finder', methods=['POST'])
def mode_3_advanced_finder():
    if not student_schedule_map: return jsonify({'error': 'Server data not loaded.'}), 500
    target_mis_set = _get_target_students(request.form)
    requested_batches = int(request.form.get('num_batches', 1))
    if not target_mis_set: return jsonify({'error': 'No students found.'}), 400
    
    # 1. Try to find a solution with the user's exact filters
    constrained_slot_pool = _parse_slot_filters(request.form, prefix="m3_")
    if not constrained_slot_pool:
        pass 

    availability_map = _get_student_availability_map(target_mis_set, constrained_slot_pool)
    solutions = _find_balanced_solutions(target_mis_set, requested_batches, availability_map)
    
    if solutions:
        return jsonify({'status': 'success', 'solutions': solutions})

    # 2. If it fails, start the two-column suggestion logic
    suggestion_more_batches = None
    suggestion_relaxed_slots = None

    # Suggestion 1: "More Batches" (using the *original* constrained availability_map)
    for i in range(requested_batches + 1, MAX_BATCH_OPTIONS + 1):
        sugg_more = _find_balanced_solutions(target_mis_set, i, availability_map)
        if sugg_more:
            suggestion_more_batches = {'solutions': sugg_more, 'batch_count': i}
            break 

    # Suggestion 2: "Relaxed Slots" (using the *original* requested_batches)
    requested_days = request.form.getlist('m3_days')
    if not requested_days: 
        requested_days = DAYS_OPTIONS
    
    day_constrained_pool = [slot for slot in all_possible_slots if slot[0] in requested_days]
    day_constrained_map = _get_student_availability_map(target_mis_set, day_constrained_pool)
    sugg_relaxed = _find_balanced_solutions(target_mis_set, requested_batches, day_constrained_map)
    
    if sugg_relaxed:
        suggestion_relaxed_slots = {'solutions': sugg_relaxed, 'type': 'days'}
    else:
        full_availability_map = _get_student_availability_map(target_mis_set, all_possible_slots)
        sugg_full = _find_balanced_solutions(target_mis_set, requested_batches, full_availability_map)
        if sugg_full:
            suggestion_relaxed_slots = {'solutions': sugg_full, 'type': 'all'}

    # 3. Return both suggestions (or neither)
    if suggestion_more_batches or suggestion_relaxed_slots:
        return jsonify({
            'status': 'failure_with_suggestion', 
            'requested_batches': requested_batches,
            'suggestion_more_batches': suggestion_more_batches,
            'suggestion_relaxed_slots': suggestion_relaxed_slots
        })

    return jsonify({'status': 'failure_no_solution', 'requested_batches': requested_batches})

@app.route('/mode_4_planner', methods=['POST'])
def mode_4_planner():
    if not student_schedule_map: return jsonify({'error': 'Server data not loaded.'}), 500
    
    target_mis_set = _get_target_students(request.form)
    requested_batches = int(request.form.get('num_batches', 1))
    if not target_mis_set: return jsonify({'error': 'No students found.'}), 400

    batch_slot_pools = []
    for i in range(requested_batches):
        prefix = f"m4_batch_{i}_"
        batch_pool = _parse_slot_filters(request.form, prefix=prefix)
        if not batch_pool:
            return jsonify({'error': f"No available time slots were found that match the constraints for Batch {i+1}."})
        batch_slot_pools.append(batch_pool)

    all_unique_slots_in_plan = set()
    for pool in batch_slot_pools:
        all_unique_slots_in_plan.update(pool)
    
    availability_map = _get_student_availability_map(target_mis_set, list(all_unique_slots_in_plan))

    cleaned_batch_slot_pools = []
    for i, pool in enumerate(batch_slot_pools):
        viable_pool = [slot for slot in pool if slot in availability_map]
        if not viable_pool:
            return jsonify({'error': f"No students are free for any slot that matches the constraints for Batch {i+1}."})

        if len(viable_pool) > TOP_N_SLOTS_HEURISTIC:
            top_slots = sorted(viable_pool, key=lambda s: len(availability_map[s]['free_students']), reverse=True)
            viable_pool = top_slots[:TOP_N_SLOTS_HEURISTIC]
            
        cleaned_batch_slot_pools.append(viable_pool)

    all_solutions = []
    
    for slot_combination in product(*cleaned_batch_slot_pools):
        
        if len(set(slot_combination)) != len(slot_combination):
            continue
            
        batches = [[] for _ in range(requested_batches)]
        student_options = {}
        
        for student in target_mis_set:
            possible_slots = []
            for i, slot in enumerate(slot_combination):
                if student in availability_map[slot]['free_students']:
                    possible_slots.append(i)
            if possible_slots:
                student_options[student] = possible_slots
        
        for student, options in sorted(student_options.items(), key=lambda item: len(item[1])):
            smallest_batch_index = min(options, key=lambda i: len(batches[i]))
            batches[smallest_batch_index].append(student)
            
        unscheduled = target_mis_set - set(s for b in batches for s in b)
        
        if not unscheduled: 
            score = np.std([len(b) for b in batches]) 
            solution_details = []
            for i, batch in enumerate(batches):
                slot = slot_combination[i]
                solution_details.append({
                    'day': slot[0], 'time': slot[1],
                    'students': students_df_global[students_df_global['MIS'].isin(batch)].drop_duplicates(subset=['MIS']).to_dict('records'),
                    'available_rooms': availability_map[slot]['available_rooms']
                })
            all_solutions.append({'score': score, 'solution': solution_details})
            
    if not all_solutions:
        full_availability_map = _get_student_availability_map(target_mis_set, all_possible_slots)
        suggestion_solutions = _find_balanced_solutions(target_mis_set, requested_batches, full_availability_map)
        
        if suggestion_solutions:
            return jsonify({'status': 'failure_with_suggestion', 'requested_batches': requested_batches, 'suggestion': {'solutions': suggestion_solutions}})
        
        return jsonify({'status': 'failure_no_solution', 'requested_batches': requested_batches})

    all_solutions.sort(key=lambda x: x['score'])
    top_solutions = [s['solution'] for s in all_solutions[:TOP_N_SOLUTIONS_TO_SHOW]]
    
    return jsonify({'status': 'success', 'solutions': top_solutions})


@app.route('/mode_5_day_finder', methods=['POST'])
def mode_5_day_finder():
    if not student_schedule_map: return jsonify({'error': 'Server data not loaded.'}), 500
    target_mis_set = _get_target_students(request.form)
    requested_batches = int(request.form.get('num_batches', 1))
    required_day = request.form.get('m5_day')
    if not target_mis_set: return jsonify({'error': 'No students found.'}), 400
    
    day_specific_pool = [slot for slot in all_possible_slots if slot[0] == required_day]
    if not day_specific_pool:
        if required_day not in DAYS_OPTIONS:
             return jsonify({'error': f'{required_day} is not a valid day.'})
        pass 
        
    availability_map = _get_student_availability_map(target_mis_set, day_specific_pool)
    solutions = _find_balanced_solutions(target_mis_set, requested_batches, availability_map)
    
    if solutions:
        return jsonify({'status': 'success', 'solutions': solutions})
        
    suggestion_pool = [slot for slot in all_possible_slots if slot[0] != required_day]
    full_availability_map = _get_student_availability_map(target_mis_set, suggestion_pool)
    suggestion_solutions_mixed = _find_balanced_solutions(target_mis_set, requested_batches, full_availability_map)
    
    other_days = [day for day in ALL_DAYS_OPTIONS if day != required_day]
    suggestion_solutions_days = []
    
    for day in other_days:
        day_pool = [slot for slot in all_possible_slots if slot[0] == day]
        if not day_pool: continue
        
        day_map = _get_student_availability_map(target_mis_set, day_pool)
        if not day_map: continue
        
        day_solutions = _find_balanced_solutions(target_mis_set, requested_batches, day_map)
        
        if day_solutions:
            suggestion_solutions_days.append(day)
            
    if suggestion_solutions_mixed or suggestion_solutions_days:
        return jsonify({
            'status': 'failure_with_suggestion', 
            'requested_day': required_day, 
            'suggestion_mixed': {'solutions': suggestion_solutions_mixed} if suggestion_solutions_mixed else None,
            'suggestion_days': suggestion_solutions_days
        })
        
    return jsonify({'status': 'failure_no_solution', 'requested_day': required_day})

# ## --- THIS IS THE MODIFIED DOWNLOAD ROUTE --- ##
@app.route('/download_list', methods=['POST'])
def download_list():
    try:
        data = request.get_json()
        mis_list = data.get('mis_list', [])
        if not mis_list:
            return jsonify({"error": "No student list provided."}), 400

        # Filter the global dataframe
        df_to_download = students_df_global[students_df_global['MIS'].isin(mis_list)].copy()
        
        # ## --- THIS IS THE FIX --- ##
        # 1. Drop duplicates to get the 41 unique students
        df_to_download.drop_duplicates(subset=['MIS'], inplace=True)
        
        # 2. Sort by MIS number
        df_to_download.sort_values(by='MIS', inplace=True)
        
        # 3. Select and reorder columns
        df_to_download = df_to_download[['MIS', 'Name', 'Branch']]
        
        # Create an in-memory Excel file
        output = io.BytesIO()

        # --- NEW AUTO-SIZING LOGIC ---
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_to_download.to_excel(writer, index=False, sheet_name='Students')
            worksheet = writer.sheets['Students']
            
            for column_cells in worksheet.columns:
                # Add 2 for padding
                length = max(len(str(cell.value)) for cell in column_cells) + 2
                column_letter = column_cells[0].column_letter
                worksheet.column_dimensions[column_letter].width = length
        # --- END NEW LOGIC ---
        
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='student_list.xlsx'
        )
    except Exception as e:
        print(f"Error generating download: {e}")
        return jsonify({"error": "Failed to generate file."}), 500

@app.route('/')
def index():
    return render_template('index.html', 
                           days=DAYS_OPTIONS, 
                           times_formatted=TIMES_OPTIONS_FORMATTED, # For "FROM" (Modes 3-5)
                           times_formatted_end=TIMES_OPTIONS_FORMATTED_END, # For "TO" (Modes 3-5)
                           times_full=TIMES_OPTIONS_FULL, # For Modes 1, 2
                           subjects=SUBJECT_OPTIONS, 
                           divisions=DIVISION_OPTIONS,
                           all_days=ALL_DAYS_OPTIONS,
                           all_possible_slots=all_possible_slots,
                           subject_division_map=subject_division_map
                           )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)