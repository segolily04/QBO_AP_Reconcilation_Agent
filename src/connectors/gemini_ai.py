# src/connectors/gemini_ai.py

import os
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load our .env file to pull the GEMINI_API_KEY into the runtime environment
load_dotenv()

# ============================================================================
# 1. DEFINE STRUCTURED SCHEMAS (Pydantic Enforcement Layer)
# ============================================================================

class RemittanceLineItem(BaseModel):
    """Represents a single invoice line item found inside a client's payment list."""
    invoice_number: str = Field(description="The explicit alphanumeric invoice number or reference code.")
    amount_invoiced: float = Field(description="The total gross amount originally billed on this invoice.")
    amount_paid: float = Field(description="The specific amount remitted/paid for this line item.")

class InvoicedExtractionResult(BaseModel):
    """The complete structured payload guaranteed to be returned by Gemini"""
    client_name: str = Field(description="The legal or commercial name of the client making the payment.")
    remittance_array: list[RemittanceLineItem] = Field(description="An array of all nested invoices listed for payment.")


# =============================================================================
# 2. CORE EXTRACTION CONNECTOR
# =============================================================================

def extract_invoice_data(pdf_file_path: str) -> InvoicedExtractionResult:
    """
    Reads a local PDF invoice file, passes its raw bytes to Gemini using a zero-trust prompt,
    and returns a fully validated Pydantic data object.
    """
    # Initialize the client. It will automatically look for os.environ["GEMINI_API_KEY"]
    client = genai.Client()

    # Read the file data into memory as bytes
    with open(pdf_file_path, "rb") as f:
        pdf_bytes = f.read()

    print(f"[GEMINI AI] Sending {os.path.basename(pdf_file_path)} to Gemini Flash for structural analysis...")

    # Strict Zero-Trust System Prompt Constraint
    system_prompt = (
        "You are an expert financial extraction agent operating under zero-trust accounting guidelines."
        "Your task is to extract payment remittance details from the provided document."
        "CRITICAL RULES:\n"
        "1. Direct Extraction Only: Extract string values and numbers EXACTLY as written in the text."
        "Do not calculate, infer, add, or extrapolate missing totals.\n"
        "2. If an invoice number is obscured or completely missing, flag it as 'UNKNOWN'. \n"
        "3. Do not attempt to guess information based on historical intuition."
    )

    # Execute the multimodal API call
    # We use gemini-2.5-flash as it is highly optimized for fast structured extraction and multimodal vision
    response = client.models.generate_content(
        model = 'gemini-2.5-flash',
        contents=[
            types.Part.from_bytes(
                data=pdf_bytes,
                mime_type="application/pdf",
            ),
            "Extract all listed invoices and payment lines from this document following your instructions."
        ],
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            # This line forces the model to respond ONLY in valid JSON matching our Pydantic class
            response_mime_type = "application/json",
            response_schema=InvoicedExtractionResult,
            temperature=0.0, # 0.0 dorces determinism, killing off creative AI behavior
        ),
    )

    # The SDK automatically handles the deserialization and populates our Pydantic object
    validated_data = response.parsed
    return validated_data