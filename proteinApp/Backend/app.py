from flask import Flask, request, jsonify
from flask_cors import CORS # pyright: ignore[reportMissingModuleSource]
import os
import mysql.connector
import json
from dotenv import load_dotenv

# Load environment variables
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
            ssl_ca=os.path.join(BASE_DIR, "ca.pem"),
            ssl_verify_cert=True,
            ssl_verify_identity=True,
            connect_timeout=20,
            use_pure=True
        )
        return connection
    except mysql.connector.Error as err:
        print(f"❌ Connection failed: {err.msg}")
        raise

# --- AUTOMATIC TABLE CREATION ---
def create_table():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
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
        if cursor: cursor.close()
        if conn: conn.close()

# --- APP CONFIGURATION ---
VALID_AMINO_ACIDS = set("ARNDCEQGHILKMFPSTWYV")
AMINO_ACID_WEIGHTS = {
    'A': 89.09,  'R': 174.20, 'N': 132.12, 'D': 133.10,
    'C': 121.15, 'Q': 146.15, 'E': 147.13, 'G': 75.07,
    'H': 155.16, 'I': 131.17, 'L': 131.17, 'K': 146.19,
    'M': 149.21, 'F': 165.19, 'P': 115.13, 'S': 105.09,
    'T': 119.12, 'W': 204.23, 'Y': 181.19, 'V': 117.15
}

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-fallback-key")
CORS(app)  # Enable CORS for Vercel

with app.app_context():
    create_table()

# --- HELPER FUNCTIONS ---
def calculate_molecular_weight(sequence):
    weight = sum(AMINO_ACID_WEIGHTS.get(aa, 0) for aa in sequence.upper())
    return round(weight, 2)

def amino_acid_frequency(sequence):
    freq = {aa: 0 for aa in VALID_AMINO_ACIDS}
    for aa in sequence.upper():
        if aa in freq:
            freq[aa] += 1
    return freq

# --- API ROUTES ---

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(force=True, silent=True) or request.form
    protein_name = data.get("protein_name", "").strip()
    sequence = data.get("sequence", "").strip().upper()

    if not protein_name or not sequence:
        return jsonify({"error": "Protein name and sequence are required."}), 400

    invalid_chars = [c for c in sequence if c not in VALID_AMINO_ACIDS]
    if invalid_chars:
        return jsonify({"error": f"Invalid characters: {', '.join(invalid_chars)}"}), 400

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
        return jsonify({"error": str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

    return jsonify({
        "message": "success",
        "data": {
            "name": protein_name,
            "length": seq_length,
            "molecular_weight": mol_weight,
            "unique_count": unique_count,
            "amino_acids": list(freq_dict.keys()),
            "frequencies": list(freq_dict.values())
        }
    })

@app.route("/search", methods=["GET"])
def search():
    query_name = request.args.get("protein_name", "").strip()
    query_sequence = request.args.get("sequence", "").strip().upper()
    
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
            
        # If no params, fetch last 20 (optional, or return empty)
        if not query_name and not query_sequence:
            sql += " ORDER BY id DESC LIMIT 20"

        cursor.execute(sql, params)
        proteins = cursor.fetchall()
        return jsonify(proteins)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.route("/protein/<int:protein_id>", methods=["GET"])
def get_protein(protein_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM proteins WHERE id=%s", (protein_id,))
        protein = cursor.fetchone()
        
        if not protein:
            return jsonify({"error": "Protein not found"}), 404
            
        return jsonify(protein)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.route("/delete/<int:protein_id>", methods=["DELETE"])
def delete_protein(protein_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM proteins WHERE id=%s", (protein_id,))
        conn.commit()
        return jsonify({"message": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.route("/edit/<int:protein_id>", methods=["POST"])
def edit_protein(protein_id):
    data = request.get_json(force=True, silent=True) or request.form
    name = data.get("protein_name", "").strip()
    sequence = data.get("sequence", "").strip().upper()

    seq_length = len(sequence)
    mol_weight = calculate_molecular_weight(sequence)
    freq_dict = amino_acid_frequency(sequence)
    unique_count = len([aa for aa in freq_dict if freq_dict[aa] > 0])
    freq_json = json.dumps(freq_dict)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE proteins SET name=%s, sequence=%s, length=%s, molecular_weight=%s, unique_count=%s, frequencies=%s WHERE id=%s",
            (name, sequence, seq_length, mol_weight, unique_count, freq_json, protein_id)
        )
        conn.commit()
        return jsonify({"message": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    app.run(debug=True)