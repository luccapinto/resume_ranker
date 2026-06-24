import re
import fitz  # PyMuPDF

def clean_text(text: str) -> str:
    """
    Cleans characters and excessive whitespace/line breaks from text.
    """
    if not text:
        return ""
    
    # Replace multiple consecutive line breaks (with optional spaces) with a single newline
    text = re.sub(r'\n\s*\n', '\n', text)
    
    # Replace multiple consecutive horizontal spaces/tabs with a single space
    text = re.sub(r'[ \t]+', ' ', text)
    
    # Filter out non-printable control characters, but keep printable ones and basic spacing
    text = "".join(ch for ch in text if ch.isprintable() or ch in '\n\r\t')
    
    return text.strip()

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extracts raw text from PDF bytes and cleans it.
    """
    try:
        # Open PDF from bytes stream
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        
        doc.close()
        return clean_text(text)
    except Exception as e:
        raise ValueError(f"Failed to parse PDF document: {str(e)}") from e
