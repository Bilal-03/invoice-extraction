import re
import io
from flask import Flask, request, jsonify, render_template
from PIL import Image
import pytesseract
import cv2
import numpy as np
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Initialize the Flask application
app = Flask(__name__)

def preprocess_image(image_stream):
    """
    Cleans and prepares the image for OCR.
    - Converts to grayscale
    - Applies a threshold to make text stand out
    """
    # Reset stream pointer
    image_stream.seek(0)

    # Convert the image stream to a NumPy array
    image_np = np.frombuffer(image_stream.read(), np.uint8)
    # Decode the image array using OpenCV
    img = cv2.imdecode(image_np, cv2.IMREAD_COLOR)
    
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Apply adaptive thresholding to get a clean, binarized image
    processed_img = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    
    return processed_img

def extract_text_from_image(processed_img):
    """
    Uses Tesseract to perform OCR on the processed image.
    """
    # Use pytesseract to extract text
    text = pytesseract.image_to_string(processed_img)
    return text

def extract_invoice_details(text):
    """
    Uses regular expressions to find key details in the OCR text.
    This simulates the NER model for a live demo.
    """
    details = {
        "invoice_number": None,
        "invoice_date": None,
        "due_date": None,
        "total_amount": None,
        "vendor_name": "Not Found" # Default value
    }

    # Regex patterns for various fields
    invoice_number_pattern = re.compile(r'(?i)(?:invoice|inv)[\s#:]*([a-z0-9-]+)')
    date_pattern = re.compile(r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\w+\s\d{1,2},\s\d{4})')
    total_amount_pattern = re.compile(r'(?i)(?:total|amount\s*due|balance)[\s:]*\$?([\d,]+\.\d{2})')
    
    lines = text.split('\n')

    # Extract Vendor Name (heuristic: use the first non-empty line)
    for line in lines:
        if line.strip():
            details["vendor_name"] = line.strip()
            break

    # Iterate through lines to find other details
    for line in lines:
        # Invoice Number
        if not details["invoice_number"]:
            match = invoice_number_pattern.search(line)
            if match:
                details["invoice_number"] = match.group(1).strip()

        # Dates
        date_matches = date_pattern.findall(line)
        if date_matches:
            found_date = date_matches[0]  # take the first match
            if "due" in line.lower() and not details["due_date"]:
                details["due_date"] = found_date
            elif not details["invoice_date"]:
                details["invoice_date"] = found_date

        # Total Amount
        if not details["total_amount"]:
            match = total_amount_pattern.search(line)
            if match:
                details["total_amount"] = match.group(1).strip()

    return details


@app.route('/', methods=['GET'])
def index():
    """Render the main upload page."""
    return render_template('index.html')

@app.route('/extract', methods=['POST'])
def extract():
    """
    The main API endpoint. Handles file upload and the extraction pipeline.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if file:
        try:
            # 1. Preprocess the image
            processed_image = preprocess_image(file.stream)
            
            # 2. Extract raw text using OCR
            raw_text = extract_text_from_image(processed_image)
            
            # 3. Extract structured details using regex
            extracted_data = extract_invoice_details(raw_text)
            
            # 4. Return the structured data as JSON
            return jsonify(extracted_data)

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": "File processing failed"}), 500

if __name__ == '__main__':
    app.run(debug=True)
