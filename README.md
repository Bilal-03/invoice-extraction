# AI-Powered Invoice Data Extraction System

An intelligent microservice that automatically extracts structured data from invoice images using Computer Vision and Natural Language Processing.

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/flask-2.3.2-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

## 🎯 Overview

This project automates invoice data extraction for enterprise procurement workflows, reducing manual data entry effort and improving accuracy. The system processes invoice images and PDFs to extract key information like invoice numbers, dates, vendor names, and amounts.

**Key Achievement:** 84% extraction accuracy across diverse invoice formats with ~4 second processing time per document.

## ✨ Features

- **Automated Data Extraction**: Extracts invoice numbers, dates, vendor names, and total amounts
- **Image Preprocessing**: Advanced OpenCV-based preprocessing (grayscale conversion, adaptive thresholding, deskewing)
- **Hybrid Extraction**: Combines regex patterns with Named Entity Recognition for robust performance
- **RESTful API**: Simple HTTP endpoint for easy integration
- **Docker Support**: Containerized for consistent deployment across environments

## 🏗️ Architecture

The system uses a 4-stage processing pipeline:

1. **Image Preprocessing** (OpenCV)
   - Grayscale conversion
   - Adaptive thresholding
   - Noise reduction
   - Deskewing

2. **Optical Character Recognition** (Tesseract)
   - Converts preprocessed images to text

3. **Data Extraction** (Regex + NER)
   - Pattern matching for structured fields
   - Context-aware entity recognition

4. **Post-Processing**
   - Data validation
   - JSON formatting

## 🛠️ Tech Stack

- **Backend**: Python 3.9+, Flask
- **Computer Vision**: OpenCV, Pillow
- **OCR**: Tesseract
- **NLP**: spaCy (for future NER implementation)
- **Containerization**: Docker

## 📦 Installation

### Prerequisites

- Python 3.9 or higher
- Tesseract OCR installed on your system

#### Install Tesseract:

**Windows:**
```bash
# Download from: https://github.com/UB-Mannheim/tesseract/wiki
# Add to PATH: C:\Program Files\Tesseract-OCR\tesseract.exe
```

**macOS:**
```bash
brew install tesseract
```

**Linux:**
```bash
sudo apt-get update
sudo apt-get install tesseract-ocr
```

### Setup

1. **Clone the repository**
```bash
git clone https://github.com/YOUR_USERNAME/invoice-extraction.git
cd invoice-extraction
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Update Tesseract path** (if needed)

Edit `app.py` line 7 to match your Tesseract installation:
```python
pytesseract.pytesseract.tesseract_cmd = r"YOUR_TESSERACT_PATH"
```

5. **Run the application**
```bash
python app.py
```

The API will be available at `http://localhost:5000`

## 🐳 Docker Deployment

```bash
# Build the Docker image
docker build -t invoice-extraction .

# Run the container
docker run -p 5000:5000 invoice-extraction
```

## 🚀 Usage

### Using the Web Interface

1. Open your browser and navigate to `http://localhost:5000`
2. Upload an invoice image (JPG, PNG)
3. View extracted data in JSON format

### Using the API

```bash
curl -X POST -F "file=@invoice.jpg" http://localhost:5000/extract
```

**Response:**
```json
{
  "invoice_number": "INV-2024-001234",
  "invoice_date": "15/01/2024",
  "due_date": "15/02/2024",
  "total_amount": "2,548.75",
  "vendor_name": "ABC Supplies Ltd"
}
```

## 📊 Performance

- **Accuracy**: 84% across diverse invoice formats
- **Processing Time**: ~4 seconds per invoice
- **Tested On**: 30+ different invoice layouts and quality levels

## 🗂️ Project Structure

```
invoice-extraction/
├── app.py                 # Main Flask application
├── templates/
│   └── index.html        # Web interface
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker configuration
├── README.md             # This file
└── .gitignore           # Git ignore rules
```

## 🔧 Configuration

### Tesseract Path
Update the Tesseract path in `app.py` based on your system:
```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"  # Windows
# pytesseract.pytesseract.tesseract_cmd = r"/usr/bin/tesseract"  # Linux/Mac
```

## 🎯 Future Enhancements

- [ ] Line-item extraction (quantities, descriptions, unit prices)
- [ ] Multi-page PDF support
- [ ] Custom trained spaCy NER model deployment
- [ ] Cloud deployment (AWS/Azure)
- [ ] Batch processing capability
- [ ] Confidence scores for extracted fields
- [ ] Support for more invoice formats

## 📝 Development Context

This project was developed during a summer internship at **Techpanion Solutions Pvt Ltd** (June 2024 - July 2024) as part of their NimbleS2P procurement platform enhancement initiative.

**Objective:** Automate manual invoice processing for enterprise clients handling thousands of invoices monthly.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👤 Author

**Bilal Choudhary**
- GitHub: [@Bilal-03](https://github.com/Bilal-03)
- LinkedIn: [bilal2012](https://linkedin.com/in/bilal2012)

## 🙏 Acknowledgments

- Techpanion Solutions Pvt Ltd for the internship opportunity
- VIT Chennai for academic support
- OpenCV, Tesseract, and spaCy communities

## 📧 Contact

For questions or feedback, please reach out via [bilal3512@gmail.com](mailto:bilal3512@gmail.com)

---

⭐ If you find this project useful, please consider giving it a star!
