import os
import json
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib import colors
import stripe

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "default-secret-key")

# Configure CORS
CORS(app)

# Configure Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")

# Configure OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Ensure the downloads directory exists
DOWNLOAD_FOLDER = os.path.join(os.getcwd(), "static", "downloads")
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Document types for real estate
DOCUMENT_TYPES = {
    "sales_contract": "Real Estate Sales Contract",
    "lease_agreement": "Residential Lease Agreement",
    "addendum": "Real Estate Contract Addendum",
    "disclosure": "Property Condition Disclosure"
}

@app.route('/')
def index():
    return render_template('index.html', document_types=DOCUMENT_TYPES, stripe_key=STRIPE_PUBLISHABLE_KEY)

@app.route('/generate-document', methods=['POST'])
def generate_document():
    """Generates a FAR/BAR-style real estate document with preview and final PDF versions."""
    try:
        # Handle both JSON and form data
        if request.is_json:
            form_data = request.json
        else:
            form_data = request.form

        # Extract data
        document_type = form_data.get('document_type', 'real_estate_document')
        buyer_name = form_data.get('buyer_name', 'Buyer')
        seller_name = form_data.get('seller_name', 'Seller')
        client_name = form_data.get('client_name', 'Client')
        property_address = form_data.get('property_address', 'Unknown Address')
        purchase_price = form_data.get('purchase_price', '0')
        closing_date = form_data.get('closing_date', 'TBD')
        party_role = form_data.get('party_role', 'N/A')
        property_state = form_data.get('property_state', 'Florida')
        transaction_type = form_data.get('transaction_type', 'Residential Purchase')
        additional_instructions = form_data.get('additional_instructions', '')

        # Optional Clauses
        clause_inspection = bool(form_data.get('clause_inspection'))
        clause_financing = bool(form_data.get('clause_financing'))
        clause_appraisal = bool(form_data.get('clause_appraisal'))
        clause_hoa = bool(form_data.get('clause_hoa'))

        # Unique file names
        unique_id = uuid.uuid4().hex[:8]
        preview_filename = f"preview_{document_type}_{unique_id}.pdf"
        final_filename = f"{document_type}_{unique_id}.pdf"

        # Refined OpenAI prompt
        prompt = f"""
Generate a professional Florida real estate contract styled after a FAR/BAR agreement. Use legal formatting, numbered sections, and clear, formal language expected in a standard real estate transaction.

Include the following fields:

- Document Type: {document_type}
- Buyer Name: {buyer_name}
- Seller Name: {seller_name}
- Property Address: {property_address}
- Purchase Price: ${purchase_price}
- Closing Date: {closing_date}
- Party Role: {party_role}
- State: {property_state}
- Transaction Type: {transaction_type}
- Optional Clauses:
    • Inspection Contingency: {clause_inspection}
    • Financing Contingency: {clause_financing}
    • Appraisal Contingency: {clause_appraisal}
    • HOA Disclosure: {clause_hoa}
- Additional Instructions: {additional_instructions}

Include all required legal disclosures and a signature section for both buyer and seller. Start with a title header, and mark the preview as 'WATERMARKED' if requested.
"""

        # Request to OpenAI
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "You are a real estate document assistant generating legally formatted contracts for Florida."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=4000
        )

        document_text = response.choices[0].message.content

        # Generate PDFs
        preview_path = os.path.join(DOWNLOAD_FOLDER, preview_filename)
        final_path = os.path.join(DOWNLOAD_FOLDER, final_filename)

        create_pdf(document_text, preview_path, client_name, DOCUMENT_TYPES.get(document_type, "Real Estate Document"), watermark=True)
        create_pdf(document_text, final_path, client_name, DOCUMENT_TYPES.get(document_type, "Real Estate Document"), watermark=False)

        return jsonify({
            'success': True,
            'preview_url': f'/download/{preview_filename}',
            'final_filename': final_filename
        })

    except Exception as e:
        app.logger.error(f"Error generating document: {str(e)}")
        return jsonify({'error': f'Failed to generate document: {str(e)}'}), 500

def create_pdf(text, filepath, client_name, document_type, watermark=False):
    """ Generates a PDF document with an optional watermark. """
    doc = SimpleDocTemplate(filepath, pagesize=letter)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, alignment=TA_CENTER, textColor=colors.navy)
    normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontSize=11, alignment=TA_JUSTIFY, leading=14)

    content = [Paragraph(f"{document_type.upper()}", title_style), Spacer(1, 20)]
    content.append(Paragraph(f"Prepared for: {client_name}", title_style))
    content.append(Spacer(1, 20))
    content.append(Paragraph(f"Date: {datetime.now().strftime('%B %d, %Y')}", normal_style))
    content.append(Spacer(1, 20))

    if watermark:
        content.append(Paragraph("<font color='red'>WATERMARKED PREVIEW</font>", title_style))
        content.append(Spacer(1, 20))

    paragraphs = text.split('\n')
for para in paragraphs:
    if para.strip():
        try:
            safe_para = para.encode('utf-8').decode('utf-8')
            content.append(Paragraph(safe_para, normal_style))
            content.append(Spacer(1, 6))
        except Exception as e:
            print(f"Encoding error: {e}")

    doc.build(content)

@app.route('/download/<filename>')
def download_file(filename):
    """ Allows users to download files. """
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """ Creates a Stripe Checkout session and links the final document filename for purchase. """
    try:
        # Handle both JSON and form data
        if request.is_json:
            data = request.json
        elif request.form:
            data = request.form
        else:
            data = request.get_json()  # Fallback to get_json() for backward compatibility
            
        final_filename = data.get("final_filename", "")

        if not final_filename:
            return jsonify({'error': 'Missing document filename'}), 400

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Real Estate Document',
                    },
                    'unit_amount': 9900,  # $99.00
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"http://127.0.0.1:5001/download/{final_filename}",
            cancel_url="http://127.0.0.1:5001/cancel",
        )
        return jsonify({'sessionId': session.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
