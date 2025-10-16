import streamlit as st
import json
import random
import string
import time

# --- DATABASE IMPORTS AND SETUP (MYSQL) ---
import mysql.connector
from mysql.connector import Error

# ⚠️ MySQL Globals (Placeholder - USER MUST UPDATE THESE) ⚠️
# Use 'host.docker.internal' if running Streamlit outside Docker but MySQL inside Docker.
# If running both inside the same Docker network, use the MySQL service name.
MYSQL_HOST = 'localhost' # Change to your Docker container host/service name if necessary
MYSQL_DATABASE = 'startup' # Ensure this database exists
MYSQL_USER = 'root'
MYSQL_PASSWORD = 'stationpassword' # Change this password!

# Simplified user_id for MySQL - acts as the CreatorUserID
user_id = 'streamlite_creator_session' 

def get_db_connection():
    """Establishes a connection to the MySQL database."""
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            database=MYSQL_DATABASE,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD
        )
        return conn
    except Error as e:
        st.error(f"Error connecting to MySQL: {e}")
        st.info(f"Please ensure your MySQL container is running and the credentials (Host: {MYSQL_HOST}, Database: {MYSQL_DATABASE}) are correct.")
        return None

# --- HELPER FUNCTIONS ---

def generate_access_code(length=6):
    """Generates a random alphanumeric access code."""
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for i in range(length))

def generate_question_data(i):
    """Generates a default structure for a new question."""
    return {
        'id': str(i),
        'text': f"Question {i} text (e.g., What is the primary polymer used in injection molding?)",
        'type': 'SINGLE_CHOICE', # Default type
        'points': 1,
        'choices': [
            {'id': 'a', 'text': 'Choice A', 'is_correct': True},
            {'id': 'b', 'text': 'Choice B', 'is_correct': False},
            {'id': 'c', 'text': 'Choice C', 'is_correct': False},
        ]
    }

def generate_subquiz_data(i):
    """Generates a default structure for a new subquiz."""
    return {
        'id': str(i),
        'title': f"Sub-Quiz Module {i}",
        'questions': [generate_question_data(1)]
    }

def score_answer(question, submitted_answer):
    """Scores a question based on its type and submitted answer."""
    score = 0
    correct = False

    if question['type'] == 'SINGLE_CHOICE':
        # submitted_answer is the ChoiceID
        correct_choice_id = next((c['id'] for c in question['choices'] if c['is_correct']), None)
        if submitted_answer == correct_choice_id:
            score = question['points']
            correct = True

    elif question['type'] == 'MULTI_SELECT':
        # submitted_answer is a list of ChoiceIDs
        correct_ids = sorted([c['id'] for c in question['choices'] if c['is_correct']])
        submitted_ids = sorted(submitted_answer)
        if correct_ids == submitted_ids:
            score = question['points']
            correct = True

    # OPEN_TEXT requires manual review
    elif question['type'] == 'OPEN_TEXT':
        score = 0
        correct = False

    return score, correct

# --- MYSQL DATA OPERATIONS ---

def get_quiz_list(user_id):
    """Fetches a list of Quizzes created by the current user."""
    conn = get_db_connection()
    if not conn: return []
    quizzes = []
    try:
        cursor = conn.cursor(dictionary=True)
        # Fetch only quizzes created by the current user
        cursor.execute("SELECT QuizID, Title FROM Quizzes WHERE CreatorUserID = %s", (user_id,))
        quizzes = [{'id': q['QuizID'], 'title': q['Title']} for q in cursor.fetchall()]
    except Error as e:
        st.error(f"MySQL Error in get_quiz_list: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()
    return quizzes

def get_quiz_by_code(access_code):
    """Fetches a quiz definition using its unique access code and reconstructs the nested structure."""
    conn = get_db_connection()
    if not conn: return None, None
    
    quiz_data = None
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # 1. Get Quiz Header
        cursor.execute("SELECT QuizID, Title, CreatorUserID FROM Quizzes WHERE Access_Code = %s", (access_code,))
        quiz_header = cursor.fetchone()
        if not quiz_header:
            return None, None
        
        quiz_id = quiz_header['QuizID']
        quiz_doc_id = str(quiz_id) # Use QuizID as the internal ID
        quiz_data = {'title': quiz_header['Title'], 'creator_id': quiz_header['CreatorUserID'], 'access_code': access_code}
        
        # 2. Get SubQuizzes
        cursor.execute("SELECT SubQuizID, Title, Order_Index FROM SubQuizzes WHERE QuizID = %s ORDER BY Order_Index", (quiz_id,))
        subquizzes_raw = cursor.fetchall()
        
        sub_quizzes = []
        for sq_raw in subquizzes_raw:
            subquiz = {'id': str(sq_raw['SubQuizID']), 'title': sq_raw['Title'], 'questions': []}
            sq_id = sq_raw['SubQuizID']
            
            # 3. Get Questions for this SubQuiz
            cursor.execute("SELECT QuestionID, Question_Text, Question_Type, Points, Order_Index FROM Questions WHERE SubQuizID = %s ORDER BY Order_Index", (sq_id,))
            questions_raw = cursor.fetchall()
            
            for q_raw in questions_raw:
                question = {
                    'id': str(q_raw['QuestionID']), 
                    'text': q_raw['Question_Text'], 
                    'type': q_raw['Question_Type'], 
                    'points': q_raw['Points'],
                    'choices': []
                }
                q_id = q_raw['QuestionID']
                
                # 4. Get Choices for this Question
                if q_raw['Question_Type'] != 'OPEN_TEXT':
                    cursor.execute("SELECT ChoiceID, Choice_Text, Is_Correct FROM Choices WHERE QuestionID = %s", (q_id,))
                    choices_raw = cursor.fetchall()
                    
                    for c_raw in choices_raw:
                        # Use short IDs (a, b, c, ...) for front-end rendering logic
                        # DB ChoiceID is used for storing the answer internally
                        choice_internal_id = ''.join(random.choices(string.ascii_lowercase, k=1))
                        question['choices'].append({
                            'id': str(c_raw['ChoiceID']), # Store DB ID for result saving
                            'text': c_raw['Choice_Text'],
                            'is_correct': bool(c_raw['Is_Correct'])
                        })
                
                subquiz['questions'].append(question)
            
            sub_quizzes.append(subquiz)
            
        # 5. Attach the reconstructed JSON structure for session state consistency
        quiz_data['sub_quizzes_json'] = json.dumps(sub_quizzes)
        
        return quiz_data, quiz_doc_id
    
    except Error as e:
        st.error(f"MySQL Error in get_quiz_by_code: {e}")
        return None, None
    finally:
        if conn and conn.is_connected():
            conn.close()

def save_quiz():
    """Saves the quiz definition to MySQL using transactional inserts across all tables."""
    conn = get_db_connection()
    if not conn: return

    # Parse data from session state
    quiz_title = st.session_state['new_quiz_title']
    sub_quizzes_data = st.session_state['sub_quizzes']
    
    try:
        conn.start_transaction()
        cursor = conn.cursor()
        
        # 1. Insert into Quizzes
        access_code = generate_access_code()
        quiz_insert_query = "INSERT INTO Quizzes (CreatorUserID, Title, Access_Code) VALUES (%s, %s, %s)"
        cursor.execute(quiz_insert_query, (user_id, quiz_title, access_code))
        quiz_id = cursor.lastrowid
        
        # 2. Insert SubQuizzes and nested data
        for sq_idx, sub_quiz in enumerate(sub_quizzes_data):
            sq_insert_query = "INSERT INTO SubQuizzes (QuizID, Title, Order_Index) VALUES (%s, %s, %s)"
            cursor.execute(sq_insert_query, (quiz_id, sub_quiz['title'], sq_idx))
            subquiz_id = cursor.lastrowid
            
            for q_idx, question in enumerate(sub_quiz['questions']):
                # 3. Insert Questions
                q_insert_query = "INSERT INTO Questions (SubQuizID, Question_Text, Question_Type, Points, Order_Index) VALUES (%s, %s, %s, %s, %s)"
                cursor.execute(q_insert_query, (subquiz_id, question['text'], question['type'], question['points'], q_idx))
                question_id = cursor.lastrowid
                
                # 4. Insert Choices
                if question['type'] != 'OPEN_TEXT':
                    for choice in question['choices']:
                        c_insert_query = "INSERT INTO Choices (QuestionID, Choice_Text, Is_Correct) VALUES (%s, %s, %s)"
                        is_correct_int = 1 if choice['is_correct'] else 0
                        cursor.execute(c_insert_query, (question_id, choice['text'], is_correct_int))

        # Commit transaction
        conn.commit()
        
        # Update session state to show success message
        st.session_state['mode'] = 'QUIZ_SAVED'
        st.session_state['last_code'] = access_code
        st.toast("Quiz saved and code generated!", icon="🎉")
        st.rerun() # Rerun after state change

    except Error as e:
        conn.rollback()
        st.error(f"Failed to save quiz due to MySQL error: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

def submit_results():
    """Calculates score and saves the final result to MySQL."""
    conn = get_db_connection()
    if not conn: return
    
    quiz_state = st.session_state['quiz_to_take']
    quiz_id = int(quiz_state['id'])
    
    # 1. Calculate Score (logic remains the same)
    total_score = 0
    all_questions_map = {} 
    
    for subquiz in quiz_state['sub_quizzes']:
        for question in subquiz['questions']:
            q_key = f"{question['id']}" # Use only the question ID as the key for simplicity
            all_questions_map[q_key] = question

    # Recalculate and prepare answers for database
    answers_to_insert = []
    
    # Flatten all questions to map session key to DB QuestionID
    question_lookup = {}
    for subquiz in quiz_state['sub_quizzes']:
        for question in subquiz['questions']:
            session_key = f"{subquiz['id']}_{question['id']}"
            question_lookup[session_key] = question

    # Process Answers
    for session_key, submitted in quiz_state['answers'].items():
        q_data = question_lookup.get(session_key)
        if not q_data: continue

        # Handle potential None answer for unanswered questions
        if submitted is None or submitted == []:
             score = 0
             correct = False
             submitted_str = "N/A"
        else:
            score, correct = score_answer(q_data, submitted)
            submitted_str = str(submitted)

        total_score += score
        
        question_id = int(q_data['id']) 
        is_correct_int = 1 if correct else 0
        
        answers_to_insert.append({
            'question_id': question_id, 
            'submitted': submitted_str, 
            'is_correct': is_correct_int, 
            'score': score
        })


    try:
        conn.start_transaction()
        cursor = conn.cursor()

        # 2. Insert into QuizTakers
        taker_name = quiz_state['taker_name']
        
        taker_insert_query = "INSERT INTO QuizTakers (QuizID, Taker_Name, Completed_At, Total_Score) VALUES (%s, %s, NOW(), %s)"
        cursor.execute(taker_insert_query, (quiz_id, taker_name, total_score))
        taker_id = cursor.lastrowid
        
        # 3. Insert into Answers
        answer_insert_query = "INSERT INTO Answers (TakerID, QuestionID, Submitted_Answer, Is_Correct, Score_Achieved) VALUES (%s, %s, %s, %s, %s)"
        
        for ans in answers_to_insert:
             cursor.execute(answer_insert_query, (taker_id, ans['question_id'], ans['submitted'], ans['is_correct'], ans['score']))

        conn.commit()
        
        st.session_state['mode'] = 'QUIZ_COMPLETE'
        st.session_state['final_score'] = total_score
        st.rerun() # Rerun after submission

    except Error as e:
        conn.rollback()
        st.error(f"Failed to submit results due to MySQL error: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

# --- STREAMLIT UI COMPONENTS ---

def creator_mode():
    st.header("Quiz Creator Dashboard")
    st.markdown(f"**Your Creator ID:** `{user_id}`")
    st.caption("Quiz data is saved to your configured MySQL database.")

    if st.button("➕ Create New Quiz"):
        st.session_state['mode'] = 'CREATE_QUIZ'
        st.session_state['new_quiz_title'] = "New Injection Molding Quiz"
        st.session_state['sub_quizzes'] = [generate_subquiz_data(1)]
        st.rerun() # Rerun to switch mode

    st.subheader("Your Quizzes")
    quizzes = get_quiz_list(user_id)
    if not quizzes:
        st.info("You haven't created any quizzes yet.")
    else:
        for quiz in quizzes:
            col1, col2, col3 = st.columns([4, 2, 1])
            col1.write(quiz['title'])
            if col2.button("👁️ View Results", key=f"view_{quiz['id']}"):
                st.session_state['mode'] = 'VIEW_RESULTS'
                st.session_state['current_quiz_id'] = quiz['id']
                st.rerun() # Rerun to switch mode
            # Removed Edit/Delete for simplicity in this refactor


def create_quiz_mode():
    st.header("Build a New Quiz")
    
    # Title
    st.session_state['new_quiz_title'] = st.text_input("Quiz Title (e.g., Injection Molding Mastery)", 
                                                       st.session_state.get('new_quiz_title', 'New Quiz'),
                                                       key="quiz_title_input")
    
    st.subheader("Sub-Quizzes and Questions")

    # Add new subquiz button
    if st.button("➕ Add New Sub-Quiz"):
        new_id = len(st.session_state['sub_quizzes']) + 1
        st.session_state['sub_quizzes'].append(generate_subquiz_data(new_id))
        st.rerun() # Rerun to render new sub-quiz structure

    # Iterate and render sub-quizzes
    for sq_idx, sub_quiz in enumerate(st.session_state['sub_quizzes']):
        with st.expander(f"Module {sq_idx + 1}: {sub_quiz['title']}", expanded=True):
            
            # Sub-Quiz Title
            sub_quiz['title'] = st.text_input("Module Title", sub_quiz['title'], key=f"sq_title_{sq_idx}")
            
            # Add Question Button
            if st.button(f"➕ Add Question to {sub_quiz['title']}", key=f"add_q_{sq_idx}"):
                new_q_id = len(sub_quiz['questions']) + 1
                sub_quiz['questions'].append(generate_question_data(new_q_id))
                st.rerun() # Rerun to render new question

            # Iterate and render questions
            for q_idx, question in enumerate(sub_quiz['questions']):
                st.markdown(f"#### Question {q_idx + 1}")
                colA, colB = st.columns([3, 1])
                
                # Question Text and Points
                question['text'] = colA.text_area("Question Text", question['text'], key=f"q_text_{sq_idx}_{q_idx}", height=68)
                question['points'] = colB.number_input("Points", 1, 10, question['points'], key=f"q_points_{sq_idx}_{q_idx}")
                
                # Question Type
                question['type'] = colB.selectbox("Type", ('SINGLE_CHOICE', 'MULTI_SELECT', 'OPEN_TEXT'), 
                                                  index=('SINGLE_CHOICE', 'MULTI_SELECT', 'OPEN_TEXT').index(question['type']), 
                                                  key=f"q_type_{sq_idx}_{q_idx}")

                # Choices rendering (only for non-open text)
                if question['type'] != 'OPEN_TEXT':
                    st.markdown("##### Choices")
                    
                    # Ensure at least 2 choices exist
                    while len(question['choices']) < 2:
                        # Regenerate choices structure if needed to maintain minimum length
                        question['choices'] = [
                            {'id': 'a', 'text': 'Choice A', 'is_correct': False},
                            {'id': 'b', 'text': 'Choice B', 'is_correct': False},
                        ]
                        st.rerun()

                    # Add choice button
                    if st.button("➕ Add Choice", key=f"add_c_{sq_idx}_{q_idx}"):
                         # Use a random ID for the session state key
                         new_choice_id = ''.join(random.choices(string.ascii_lowercase, k=1))
                         question['choices'].append({'id': new_choice_id, 'text': f"Choice {new_choice_id.upper()}", 'is_correct': False})
                         st.rerun()

                    for c_idx, choice in enumerate(question['choices']):
                        colC, colD, colE = st.columns([0.5, 4, 1])
                        
                        is_correct = colC.checkbox("Correct", choice['is_correct'], key=f"c_corr_{sq_idx}_{q_idx}_{c_idx}")
                        choice['is_correct'] = is_correct

                        choice['text'] = colD.text_input("Choice Text", choice['text'], key=f"c_text_{sq_idx}_{q_idx}_{c_idx}")

                        if colE.button("X", key=f"del_c_{sq_idx}_{q_idx}_{c_idx}"):
                            del question['choices'][c_idx]
                            st.rerun()

    st.markdown("---")
    if st.button("💾 Save and Generate Code", type="primary"):
        save_quiz()

def quiz_saved_mode():
    st.success("Your Quiz has been successfully created!")
    st.header(f"Quiz Title: {st.session_state['new_quiz_title']}")
    st.subheader("Shareable Access Code")
    
    code = st.session_state.get('last_code', 'ERROR')
    st.code(code, language='text')
    st.info("Share this code with participants. They can use it in the 'Take Quiz' mode.")
    
    if st.button("⬅️ Back to Dashboard"):
        st.session_state['mode'] = 'CREATOR'
        st.rerun() # Rerun to switch mode

def taker_mode():
    st.header("Take a Quiz")
    
    if 'quiz_to_take' not in st.session_state:
        st.subheader("Enter Quiz Access Code")
        
        access_code = st.text_input("Access Code").strip().upper()
        if st.button("Find Quiz"):
            if access_code:
                quiz_data, quiz_doc_id = get_quiz_by_code(access_code)
                if quiz_data:
                    # quiz_data['sub_quizzes_json'] holds the nested structure, load it
                    sub_quizzes_data = json.loads(quiz_data['sub_quizzes_json'])

                    # Prepare choices for UI consumption
                    for sq in sub_quizzes_data:
                        for q in sq['questions']:
                            if q['type'] != 'OPEN_TEXT':
                                temp_choices = []
                                for idx, choice in enumerate(q['choices']):
                                    # Assign a simple UI key (a, b, c)
                                    choice['ui_id'] = string.ascii_lowercase[idx]
                                    temp_choices.append(choice)
                                q['choices'] = temp_choices

                    st.session_state['quiz_to_take'] = {
                        'id': quiz_doc_id, # DB QuizID
                        'data': quiz_data,
                        'sub_quizzes': sub_quizzes_data,
                        'taker_name': '',
                        'answers': {},
                        'current_step': 'NAME_INPUT'
                    }
                    st.rerun() # Rerun to move to NAME_INPUT
                else:
                    st.error("No quiz found with that code.")
            else:
                st.warning("Please enter an access code.")
    
    elif st.session_state['quiz_to_take']['current_step'] == 'NAME_INPUT':
        quiz = st.session_state['quiz_to_take']['data']
        st.subheader(f"Starting Quiz: {quiz['title']}")
        
        st.session_state['quiz_to_take']['taker_name'] = st.text_input("Enter your full name to begin")
        
        if st.session_state['quiz_to_take']['taker_name'] and st.button("Start Quiz", type="primary"):
            st.session_state['quiz_to_take']['current_step'] = 'QUIZ_ACTIVE'
            st.session_state['quiz_to_take']['current_subquiz_index'] = 0
            st.session_state['quiz_to_take']['current_question_index'] = 0
            st.rerun() # Rerun to move to QUIZ_ACTIVE

    elif st.session_state['quiz_to_take']['current_step'] == 'QUIZ_ACTIVE':
        quiz_state = st.session_state['quiz_to_take']
        sub_quizzes = quiz_state['sub_quizzes']
        sq_idx = quiz_state['current_subquiz_index']
        q_idx = quiz_state['current_question_index']

        # Check for Sub-Quiz completion
        if sq_idx >= len(sub_quizzes):
            # All done!
            submit_results()
            return

        current_subquiz = sub_quizzes[sq_idx]

        # Check for Question completion within Sub-Quiz
        if q_idx >= len(current_subquiz['questions']):
            # Move to the next sub-quiz
            st.session_state['quiz_to_take']['current_subquiz_index'] += 1
            st.session_state['quiz_to_take']['current_question_index'] = 0
            st.rerun() # ⬅️ CRITICAL FIX: Rerun to render the new sub-quiz state
            return

        current_question = current_subquiz['questions'][q_idx]

        # Display progress
        total_questions = sum(len(sq['questions']) for sq in sub_quizzes)
        questions_completed = sum(len(sub_quizzes[i]['questions']) for i in range(sq_idx)) + q_idx
        
        st.progress(questions_completed / total_questions, 
                    text=f"Module: {current_subquiz['title']} | Question {questions_completed + 1} of {total_questions} total")
        
        st.markdown(f"### Q{questions_completed + 1}: {current_question['text']} (Type: {current_question['type']}, {current_question['points']} pts)")
        
        # Key uses DB IDs for unambiguous identification during submission
        question_key = f"{current_subquiz['id']}_{current_question['id']}" 
        answer_db_id = None

        if current_question['type'] == 'SINGLE_CHOICE':
            choice_options = {}
            # Map simple UI char (a, b, c) to DB Choice ID
            for c in current_question['choices']:
                choice_options[c['ui_id']] = c['text']
            
            # The radio button returns the selected UI key (a, b, c)
            selected_ui_key = st.radio("Select one correct answer:", 
                                     options=list(choice_options.keys()), 
                                     format_func=lambda x: f"{x.upper()}. {choice_options[x]}",
                                     key=question_key)

            if selected_ui_key:
                # Find the DB ChoiceID that corresponds to the selected UI key
                selected_choice = next((c for c in current_question['choices'] if c['ui_id'] == selected_ui_key), None)
                answer_db_id = selected_choice['id'] if selected_choice else None
        
        elif current_question['type'] == 'MULTI_SELECT':
            selected_db_ids = []
            st.markdown("Select all correct answers:")
            for c in current_question['choices']:
                if st.checkbox(f"{c['ui_id'].upper()}. {c['text']}", key=f"{question_key}_{c['ui_id']}"):
                    selected_db_ids.append(c['id'])
            answer_db_id = selected_db_ids if selected_db_ids else []
        
        elif current_question['type'] == 'OPEN_TEXT':
            answer_db_id = st.text_area("Your Answer (will be manually reviewed):", key=question_key)

        # Store the answer (using the DB Choice ID or text/list of IDs) temporarily
        st.session_state['quiz_to_take']['answers'][question_key] = answer_db_id

        if st.button("Next Question", type="primary"):
            st.session_state['quiz_to_take']['current_question_index'] += 1
            st.rerun() # ⬅️ CRITICAL FIX: Rerun to render the next question


def quiz_complete_mode():
    st.balloons()
    st.success("🎉 Quiz Completed! Thank you for participating.")
    st.header(f"Your Score: {st.session_state.get('final_score', 'N/A')} points.")
    st.info("The quiz creator can now view your detailed results using their Creator Dashboard.")
    
    if st.button("Start New Quiz"):
        for key in ['quiz_to_take', 'final_score']:
            if key in st.session_state:
                del st.session_state[key]
        st.session_state['mode'] = 'HOME'
        st.rerun() # Rerun to switch mode

def view_results_mode():
    conn = get_db_connection()
    if not conn: return
    
    quiz_id = st.session_state['current_quiz_id'] 

    st.header("Results Dashboard")

    try:
        cursor = conn.cursor(dictionary=True)
        
        # 1. Fetch Quiz Header
        cursor.execute("SELECT Title, Access_Code FROM Quizzes WHERE QuizID = %s", (quiz_id,))
        quiz_header = cursor.fetchone()
        if not quiz_header:
            st.error("Quiz not found.")
            if st.button("⬅️ Back to Dashboard"): st.session_state['mode'] = 'CREATOR'; st.rerun()
            return

        st.subheader(f"Quiz: {quiz_header['Title']}")
        st.markdown(f"**Access Code:** `{quiz_header['Access_Code']}`")

        # 2. Fetch all takers (Summary data)
        takers_query = "SELECT TakerID, Taker_Name, Total_Score, Completed_At FROM QuizTakers WHERE QuizID = %s ORDER BY Total_Score DESC"
        cursor.execute(takers_query, (quiz_id,))
        all_results_summary = cursor.fetchall()

        st.markdown(f"### 📊 Total Participants: {len(all_results_summary)}")
        
        if not all_results_summary:
            st.info("No results have been submitted yet.")
        else:
            # Display summary table
            summary_data = [
                {'TakerID': r['TakerID'], 'Taker': r['Taker_Name'], 'Score': r['Total_Score'], 'Completed': r['Completed_At'].strftime('%Y-%m-%d %H:%M')}
                for r in all_results_summary
            ]
            st.dataframe(summary_data, use_container_width=True)

            # 3. Detailed results per taker
            st.markdown("---")
            for result_summary in all_results_summary:
                taker_id = result_summary['TakerID']
                
                with st.expander(f"Detailed Results for: {result_summary['Taker_Name']} (Score: {result_summary['Total_Score']})"):
                    # Join Answers, Questions, and SubQuizzes
                    detailed_answers_query = """
                        SELECT 
                            SQ.Title AS subquiz_title, 
                            Q.Question_Text AS q_text, 
                            Q.Question_Type AS q_type,
                            Q.Points AS points,
                            A.Submitted_Answer AS submitted,
                            A.Score_Achieved AS score_achieved,
                            A.Is_Correct AS is_correct
                        FROM Answers A
                        JOIN Questions Q ON A.QuestionID = Q.QuestionID
                        JOIN SubQuizzes SQ ON Q.SubQuizID = SQ.SubQuizID
                        WHERE A.TakerID = %s
                        ORDER BY SQ.Order_Index, Q.Order_Index
                    """
                    cursor.execute(detailed_answers_query, (taker_id,))
                    detailed_answers = cursor.fetchall()
                    
                    for answer in detailed_answers:
                        st.markdown(f"**[{answer['subquiz_title']}] Q: {answer['q_text']}**")
                        
                        score_color = "green" if answer['is_correct'] else "red"
                        
                        st.markdown(f"**Submitted Answer:** `{answer['submitted']}`")
                        st.markdown(f"**Status:** :{score_color}[{answer['score_achieved']} / {answer['points']} points]")
                    
                    st.markdown("---")

    except Error as e:
        st.error(f"Error viewing results from MySQL: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

    if st.button("⬅️ Back to Dashboard", key="back_from_results"):
        st.session_state['mode'] = 'CREATOR'
        st.rerun() # Rerun to switch mode

# --- MAIN APP LOGIC ---

def main():
    st.set_page_config(layout="wide", page_title="Injection Molding Quiz App")
    
    st.sidebar.title("Quiz App Navigation")
    
    if 'mode' not in st.session_state:
        st.session_state['mode'] = 'HOME'

    # Navigation buttons trigger a re-run to update the mode
    if st.sidebar.button("🏠 Home", key="nav_home"):
        st.session_state['mode'] = 'HOME'
        st.rerun()
    if st.sidebar.button("🧑‍💻 Creator Mode", key="nav_creator"):
        st.session_state['mode'] = 'CREATOR'
        st.rerun()
    if st.sidebar.button("📝 Take Quiz", key="nav_taker"):
        st.session_state['mode'] = 'TAKER'
        st.rerun()


    if st.session_state['mode'] == 'HOME':
        st.title("Collaborative Quiz Application (MySQL Backend)")
        st.markdown("Welcome! Choose your role from the sidebar:")
        st.info("""
            1. **Creator Mode:** Design a multi-module quiz and get a shareable access code.
            2. **Take Quiz:** Enter an access code to take a quiz.
        """)
        st.markdown(f"**Backend:** MySQL ({MYSQL_HOST}/{MYSQL_DATABASE})")
        st.markdown(f"**Creator Session ID:** `{user_id}`")


    elif st.session_state['mode'] == 'CREATOR':
        creator_mode()

    elif st.session_state['mode'] == 'TAKER':
        taker_mode()
        
    elif st.session_state['mode'] == 'CREATE_QUIZ':
        create_quiz_mode()
        
    elif st.session_state['mode'] == 'QUIZ_SAVED':
        quiz_saved_mode()

    elif st.session_state['mode'] == 'QUIZ_COMPLETE':
        quiz_complete_mode()
        
    elif st.session_state['mode'] == 'VIEW_RESULTS':
        view_results_mode()


if __name__ == '__main__':
    main()
