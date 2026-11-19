def get_user(cursor, user_id):
    cursor.execute("SELECT * FROM users WHERE id = " + user_id)
    return cursor.fetchone()
