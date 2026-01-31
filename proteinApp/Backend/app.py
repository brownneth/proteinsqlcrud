from flask import Flask, render_template, request, redirect
import os
import mysql.connector
import json


def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",       # default XAMPP MySQL user
        password="",       # default XAMPP MySQL password
        database="protein_db"
    )


VALID_AMINO_ACIDS = set("ARNDCEQGHILKMFPSTWYV")

# Average molecular weights of amino acids (in Daltons)
AMINO_ACID_WEIGHTS = {
    'A': 89.09,  'R': 174.20, 'N': 132.12, 'D': 133.10,
    'C': 121.15, 'Q': 146.15, 'E': 147.13, 'G': 75.07,
    'H': 155.16, 'I': 131.17, 'L': 131.17, 'K': 146.19,
    'M': 149.21, 'F': 165.19, 'P': 115.13, 'S': 105.09,
    'T': 119.12, 'W': 204.23, 'Y': 181.19, 'V': 117.15
}

def calculate_molecular_weight(sequence):
    sequence = sequence.upper()
    weight = 0
    for aa in sequence:
        weight += AMINO_ACID_WEIGHTS.get(aa, 0)
    return round(weight, 2)

def amino_acid_frequency(sequence):
    sequence = sequence.upper()
    freq = {aa: 0 for aa in VALID_AMINO_ACIDS}
    for aa in sequence:
        if aa in freq:
            freq[aa] += 1
    return freq

def is_valid_sequence(sequence):
    sequence = sequence.upper()

    for char in sequence:
        if char not in VALID_AMINO_ACIDS:
            return False

    return True


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "../frontend/templates"),
    static_folder=os.path.join(BASE_DIR, "../frontend/static")   
)

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/input")
def input_page():
    return render_template("input.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    protein_name = request.form.get("protein_name")
    sequence = request.form.get("sequence")

    if not protein_name or not sequence:
        return render_template(
            "input.html",
            error_message="Protein name and sequence are required."
        )

    sequence = sequence.upper().strip()

    # Validation
    invalid_chars = [c for c in sequence if c not in VALID_AMINO_ACIDS]
    if invalid_chars:
        return render_template(
            "input.html",
            error_message=f"Sequence contains invalid characters: {', '.join(invalid_chars)}"
        )

    # Properties
    seq_length = len(sequence)
    mol_weight = calculate_molecular_weight(sequence)
    freq_dict = amino_acid_frequency(sequence)
    unique_count = len([aa for aa in freq_dict if freq_dict[aa] > 0])

    freq_json = json.dumps(freq_dict)

    # Save to DB
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
     "INSERT INTO proteins (name, sequence, length, molecular_weight, unique_count, frequencies) VALUES (%s, %s, %s, %s, %s, %s)",
        (protein_name, sequence, seq_length, mol_weight, unique_count, freq_json)
    )
    conn.commit()
    cursor.close()
    conn.close()

    # Prepare data for chart
    amino_acids = list(freq_dict.keys())
    frequencies = list(freq_dict.values())

    return render_template(
        "results.html",
        protein_name=protein_name,
        length=seq_length,
        molecular_weight=mol_weight,
        unique_count=unique_count,
        amino_acids=amino_acids,
        frequencies=frequencies
    )


@app.route("/search", methods=["GET", "POST"])
def search():
    query_name = ""
    query_sequence = ""
    proteins = []

    if request.method == "POST":
        query_name = request.form.get("protein_name", "").strip()
        query_sequence = request.form.get("sequence", "").strip().upper()

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Build SQL query dynamically
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
        cursor.close()
        conn.close()

    return render_template(
        "search.html",
        proteins=proteins,
        query_name=query_name,
        query_sequence=query_sequence
    )

@app.route("/info")
def info_page():
        return render_template("info.html")

@app.route("/protein/<int:protein_id>")
def view_protein(protein_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM proteins WHERE id=%s", (protein_id,))
    protein = cursor.fetchone()
    cursor.close()
    conn.close()

    if not protein:
        return "Protein not found", 404

    # Prepare data for chart
    import json
    freq_dict = json.loads(protein['frequencies'])
    amino_acids = list(freq_dict.keys())
    frequencies = list(freq_dict.values())

    return render_template(
        "results.html",
        protein_name=protein['name'],
        length=protein['length'],
        molecular_weight=protein['molecular_weight'],
        unique_count=protein['unique_count'],
        amino_acids=amino_acids,
        frequencies=frequencies
    )


@app.route("/delete/<int:protein_id>", methods=["POST"])
def delete_protein(protein_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM proteins WHERE id=%s", (protein_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect("/search")
@app.route("/edit/<int:protein_id>", methods=["GET", "POST"])
def edit_protein(protein_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch protein
    cursor.execute("SELECT * FROM proteins WHERE id=%s", (protein_id,))
    protein = cursor.fetchone()

    if not protein:
        cursor.close()
        conn.close()
        return "Protein not found", 404

    if request.method == "POST":
        # Get updated values
        name = request.form.get("protein_name").strip()
        sequence = request.form.get("sequence").strip().upper()

        # Validation
        invalid_chars = [c for c in sequence if c not in VALID_AMINO_ACIDS]
        if invalid_chars:
            cursor.close()
            conn.close()
            return f"Invalid characters: {', '.join(invalid_chars)}"

        # Recalculate properties
        length = len(sequence)
        molecular_weight = calculate_molecular_weight(sequence)
        freq_dict = amino_acid_frequency(sequence)
        unique_count = len([aa for aa in freq_dict if freq_dict[aa] > 0])
        freq_json = json.dumps(freq_dict)

        # Update DB
        cursor.execute(
            "UPDATE proteins SET name=%s, sequence=%s, length=%s, molecular_weight=%s, unique_count=%s, frequencies=%s WHERE id=%s",
            (name, sequence, length, molecular_weight, unique_count, freq_json, protein_id)
        )
        conn.commit()
        cursor.close()
        conn.close()

        return redirect(f"/protein/{protein_id}")  # Show updated results

    cursor.close()
    conn.close()

    # GET → render form
    return render_template("edit.html", protein=protein)


if __name__ == "__main__":
    app.run(debug=True)
