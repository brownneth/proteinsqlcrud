from flask import Flask, render_template, request, redirect, flash
import os
import mysql.connector
import json
from dotenv import load_dotenv

# Load environment variables (local development only)
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- DATABASE CONNECTION ---
def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST", "bme512-mysql-igm4emperor-d381.h.aivencloud.com"),
            port=int(os.getenv("DB_PORT", "23377")),
            user=os.getenv("DB_USER", "avnadmin"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME", "defaultdb"),
            ssl_ca=os.path.join(BASE_DIR, "ca.pem"),  # Ensure ca.pem is in the Backend folder
            ssl_verify_cert=True,
            ssl_verify_identity=True,
            connect_timeout=20,
            use_pure=True
        )
        return connection
    except mysql.connector.Error as err:
        print(f"❌ Connection failed: {err.msg} (errno: {err.errno})")
        raise

# --- AUTOMATIC TABLE CREATION ---
def create_table():
    """Creates the proteins table if it does not exist."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # SQL from your sqlcommands.txt, modified to be 'IF NOT EXISTS'
        create_table_query = """
        CREATE TABLE IF NOT EXISTS proteins (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            sequence TEXT NOT NULL,
            length INT NOT NULL,
            molecular_weight FLOAT NOT NULL,
            unique_count INT NOT NULL,
            frequencies TEXT NOT NULL
        );
        """
        cursor.execute(create_table_query)
        conn.commit()
        print("✅ Table 'proteins' checked/created successfully.")
        
    except Exception as e:
        print(f"❌ Failed to create table: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# --- APP CONFIGURATION ---
VALID_AMINO_ACIDS = set("ARNDCEQGHILKMFPSTWYV")

AMINO_ACID_WEIGHTS = {
    'A': 89.09,  'R': 174.20, 'N': 132.12, 'D': 133.10,
    'C': 121.15, 'Q': 146.15, 'E': 147.13, 'G': 75.07,
    'H': 155.16, 'I': 131.17, 'L': 131.17, 'K': 146.19,
    'M': 149.21, 'F': 165.19, 'P': 115.13, 'S': 105.09,
    'T': 119.12, 'W': 204.23, 'Y': 181.19, 'V': 117.15
}

def calculate_molecular_weight(sequence):
    sequence = sequence.upper()
    weight = sum(AMINO_ACID_WEIGHTS.get(aa, 0) for aa in sequence)
    return round(weight, 2)

def amino_acid_frequency(sequence):
    sequence = sequence.upper()
    freq = {aa: 0 for aa in VALID_AMINO_ACIDS}
    for aa in sequence:
        if aa in freq:
            freq[aa] += 1
    return freq

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "../frontend/templates"),
    static_folder=os.path.join(BASE_DIR, "../frontend/static")
)

app.secret_key = os.getenv("SECRET_KEY", "dev-fallback-key")

# --- INITIALIZATION ---
# This runs once when the app starts, creating the table automatically
with app.app_context():
    create_table()

# --- ROUTES ---
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/input")
def input_page():
    return render_template("input.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    protein_name = request.form.get("protein_name", "").strip()
    sequence = request.form.get("sequence", "").strip()

    if not protein_name or not sequence:
        flash("Protein name and sequence are required.", "danger")
        return render_template("input.html")

    sequence = sequence.upper()
    invalid_chars = [c for c in sequence if c not in VALID_AMINO_ACIDS]
    
    if invalid_chars:
        flash(f"Invalid characters: {', '.join(invalid_chars)}", "danger")
        return render_template("input.html")

    seq_length = len(sequence)
    mol_weight = calculate_molecular_weight(sequence)
    freq_dict = amino_acid_frequency(sequence)
    unique_count = len([aa for aa in freq_dict if freq_dict[aa] > 0])
    freq_json = json.dumps(freq_dict)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO proteins (name, sequence, length, molecular_weight, unique_count, frequencies) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (protein_name, sequence, seq_length, mol_weight, unique_count, freq_json)
        )
        conn.commit()
    except Exception as e:
        flash(f"Database error: {str(e)}", "danger")
        return render_template("input.html")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

    flash("Protein analyzed and saved successfully!", "success")
    
    return render_template(
        "results.html",
        protein_name=protein_name,
        length=seq_length,
        molecular_weight=mol_weight,
        unique_count=unique_count,
        amino_acids=list(freq_dict.keys()),
        frequencies=list(freq_dict.values())
    )

@app.route("/search", methods=["GET", "POST"])
def search():
    query_name = ""
    query_sequence = ""
    proteins = []

    if request.method == "POST":
        query_name = request.form.get("protein_name", "").strip()
        query_sequence = request.form.get("sequence", "").strip().upper()

        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            sql = "SELECT * FROM proteins WHERE 1=1"
            params = []

            if query_name:
                sql += " AND name LIKE %s"
                params.append(f"%{query_name}%")
            if query_sequence:
                sql += " AND sequence LIKE %s"
                params.append(f"%{query_sequence}%")

            cursor.execute(sql, params)
            proteins = cursor.fetchall()
        except Exception as e:
            flash(f"Search failed: {str(e)}", "danger")
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    return render_template("search.html", proteins=proteins, query_name=query_name, query_sequence=query_sequence)

@app.route("/info")
def info_page():
    return render_template("info.html")

@app.route("/protein/<int:protein_id>")
def view_protein(protein_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM proteins WHERE id=%s", (protein_id,))
        protein = cursor.fetchone()

        if not protein:
            flash("Protein not found", "danger")
            return redirect("/search")

        freq_dict = json.loads(protein['frequencies'])
        return render_template(
            "results.html",
            protein_name=protein['name'],
            length=protein['length'],
            molecular_weight=protein['molecular_weight'],
            unique_count=protein['unique_count'],
            amino_acids=list(freq_dict.keys()),
            frequencies=list(freq_dict.values())
        )
    except Exception as e:
        flash(f"Error loading protein: {str(e)}", "danger")
        return redirect("/search")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.route("/delete/<int:protein_id>", methods=["POST"])
def delete_protein(protein_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM proteins WHERE id=%s", (protein_id,))
        conn.commit()
        flash("Protein deleted successfully!", "success")
    except Exception as e:
        flash(f"Delete failed: {str(e)}", "danger")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
    return redirect("/search")

@app.route("/edit/<int:protein_id>", methods=["GET", "POST"])
def edit_protein(protein_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if request.method == "POST":
            name = request.form.get("protein_name", "").strip()
            sequence = request.form.get("sequence", "").strip().upper()
            
            invalid_chars = [c for c in sequence if c not in VALID_AMINO_ACIDS]
            if invalid_chars:
                flash(f"Invalid characters: {', '.join(invalid_chars)}", "danger")
                return redirect(f"/edit/{protein_id}")

            length = len(sequence)
            mol_weight = calculate_molecular_weight(sequence)
            freq_dict = amino_acid_frequency(sequence)
            unique_count = len([aa for aa in freq_dict if freq_dict[aa] > 0])
            freq_json = json.dumps(freq_dict)

            cursor.execute(
                "UPDATE proteins SET name=%s, sequence=%s, length=%s, molecular_weight=%s, unique_count=%s, frequencies=%s WHERE id=%s",
                (name, sequence, length, mol_weight, unique_count, freq_json, protein_id)
            )
            conn.commit()
            flash("Protein updated successfully!", "success")
            return redirect(f"/protein/{protein_id}")

        cursor.execute("SELECT * FROM proteins WHERE id=%s", (protein_id,))
        protein = cursor.fetchone()
        if not protein:
            return redirect("/search")
            
        return render_template("edit.html", protein=protein)

    except Exception as e:
        flash(f"Edit error: {str(e)}", "danger")
        return redirect("/search")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    app.run(debug=debug_mode)