from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import os
import mysql.connector
import json
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-fallback-key")

# --- CRITICAL: ROBUST CORS SETUP ---
# This explicitly allows Vercel to read responses, even errors
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# --- DATABASE CONNECTION ---
def get_db_connection():
    # Verify CA file exists to prevent silent failures
    ca_path = os.path.join(BASE_DIR, "ca.pem")
    if not os.path.exists(ca_path):
        print(f"❌ Error: ca.pem not found at {ca_path}")
        raise FileNotFoundError("SSL Certificate ca.pem is missing")

    try:
        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST", "bme512-mysql-igm4emperor-d381.h.aivencloud.com"),
            port=int(os.getenv("DB_PORT", "23377")),
            user=os.getenv("DB_USER", "avnadmin"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME", "defaultdb"),
            ssl_ca=ca_path,
            ssl_verify_cert=True,
            ssl_verify_identity=True,
            connect_timeout=10, 
            use_pure=True
        )
        return connection
    except mysql.connector.Error as err:
        print(f"❌ DB Connection failed: {err}")
        raise

# --- ERROR HANDLERS ---
# These catch server crashes and send JSON instead of HTML
@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal Server Error", "details": str(error)}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({"error": str(e)}), 500

# --- HEALTH CHECK ENDPOINT ---
# Visit /health to prove the server is running
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "active", "message": "Backend is running!"}), 200

# --- AUTOMATIC TABLE CREATION ---
def create_table():
    conn = None
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
        print("✅ Table 'proteins' checked/created.")
    except Exception as e:
        print(f"❌ Table creation warning: {e}")
    finally:
        if conn and conn.is_connected(): conn.close()

# Initialize DB on start
with app.app_context():
    create_table()

# --- HELPER FUNCTIONS ---
VALID_AMINO_ACIDS = set("ARNDCEQGHILKMFPSTWYV")
AMINO_ACID_WEIGHTS = {
    'A': 89.09,  'R': 174.20, 'N': 132.12, 'D': 133.10,
    'C': 121.15, 'Q': 146.15, 'E': 147.13, 'G': 75.07,
    'H': 155.16, 'I': 131.17, 'L': 131.17, 'K': 146.19,
    'M': 149.21, 'F': 165.19, 'P': 115.13, 'S': 105.09,
    'T': 119.12, 'W': 204.23, 'Y': 181.19, 'V': 117.15
}

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

@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return _build_cors_preflight_response()

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

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO proteins (name, sequence, length, molecular_weight, unique_count, frequencies) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (protein_name, sequence, seq_length, mol_weight, unique_count, freq_json)
        )
        conn.commit()
        cursor.close()
    except Exception as e:
        return jsonify({"error": f"Database Error: {str(e)}"}), 500
    finally:
        if conn and conn.is_connected(): conn.close()

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
    
    conn = None
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
            
        if not query_name and not query_sequence:
            sql += " ORDER BY id DESC LIMIT 20"

        cursor.execute(sql, params)
        proteins = cursor.fetchall()
        cursor.close()
        return jsonify(proteins)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn and conn.is_connected(): conn.close()

@app.route("/protein/<int:protein_id>", methods=["GET"])
def get_protein(protein_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM proteins WHERE id=%s", (protein_id,))
        protein = cursor.fetchone()
        cursor.close()
        
        if not protein:
            return jsonify({"error": "Protein not found"}), 404
            
        return jsonify(protein)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn and conn.is_connected(): conn.close()

@app.route("/delete/<int:protein_id>", methods=["DELETE", "OPTIONS"])
def delete_protein(protein_id):
    if request.method == "OPTIONS":
        return _build_cors_preflight_response()
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM proteins WHERE id=%s", (protein_id,))
        conn.commit()
        cursor.close()
        return jsonify({"message": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn and conn.is_connected(): conn.close()

@app.route("/edit/<int:protein_id>", methods=["POST", "OPTIONS"])
def edit_protein(protein_id):
    if request.method == "OPTIONS":
        return _build_cors_preflight_response()

    data = request.get_json(force=True, silent=True) or request.form
    name = data.get("protein_name", "").strip()
    sequence = data.get("sequence", "").strip().upper()

    seq_length = len(sequence)
    mol_weight = calculate_molecular_weight(sequence)
    freq_dict = amino_acid_frequency(sequence)
    unique_count = len([aa for aa in freq_dict if freq_dict[aa] > 0])
    freq_json = json.dumps(freq_dict)

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE proteins SET name=%s, sequence=%s, length=%s, molecular_weight=%s, unique_count=%s, frequencies=%s WHERE id=%s",
            (name, sequence, seq_length, mol_weight, unique_count, freq_json, protein_id)
        )
        conn.commit()
        cursor.close()
        return jsonify({"message": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn and conn.is_connected(): conn.close()

def _build_cors_preflight_response():
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "*")
    response.headers.add("Access-Control-Allow-Methods", "*")
    return response

if __name__ == "__main__":
    app.run(debug=True)