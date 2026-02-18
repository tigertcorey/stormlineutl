"""
PDF processing module for Stormline UTL Bot.
Handles PDF text extraction, image extraction, and OCR for construction plans.
"""

import logging
import tempfile
import os
from typing import Dict, List, Optional
from pathlib import Path
import PyPDF2
from pdf2image import convert_from_path
from PIL import Image
import pytesseract

logger = logging.getLogger(__name__)


class PDFProcessor:
    """Handles PDF processing for construction plan takeoff."""
    
    def __init__(self):
        """Initialize PDF processor."""
        logger.info("PDF processor initialized")
    
    async def process_pdf(self, pdf_path: str) -> Dict[str, any]:
        """
        Process a PDF file and extract text and images.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Dictionary containing extracted text, page count, and images
        """
        try:
            logger.info(f"Processing PDF: {pdf_path}")
            
            result = {
                'text': '',
                'page_count': 0,
                'pages_text': [],
                'has_text': False,
                'is_scanned': False
            }
            
            # Extract text from PDF
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                result['page_count'] = len(pdf_reader.pages)
                
                for page_num, page in enumerate(pdf_reader.pages):
                    page_text = page.extract_text()
                    result['pages_text'].append({
                        'page_number': page_num + 1,
                        'text': page_text
                    })
                    result['text'] += f"\n--- Page {page_num + 1} ---\n{page_text}"
            
            # Determine if PDF has extractable text
            text_length = len(result['text'].strip())
            result['has_text'] = text_length > 100
            result['is_scanned'] = not result['has_text']
            
            logger.info(
                f"PDF processed: {result['page_count']} pages, "
                f"{'text-based' if result['has_text'] else 'scanned/image-based'}"
            )
            
            # If PDF is scanned (no text), attempt OCR
            if result['is_scanned']:
                logger.info("PDF appears to be scanned, attempting OCR...")
                ocr_text = await self._perform_ocr(pdf_path)
                result['text'] += f"\n\n--- OCR Extracted Text ---\n{ocr_text}"
                result['has_text'] = len(ocr_text.strip()) > 50
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing PDF: {e}")
            raise
    
    async def _perform_ocr(self, pdf_path: str) -> str:
        """
        Perform OCR on a PDF file.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Extracted text from OCR
        """
        try:
            # Convert PDF to images
            images = convert_from_path(pdf_path, dpi=200, first_page=1, last_page=3)
            
            ocr_text = ""
            for i, image in enumerate(images):
                logger.info(f"Performing OCR on page {i + 1}")
                page_text = pytesseract.image_to_string(image)
                ocr_text += f"\n--- Page {i + 1} (OCR) ---\n{page_text}"
            
            logger.info(f"OCR completed, extracted {len(ocr_text)} characters")
            return ocr_text
            
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return "OCR processing failed. PDF may require manual review."
    
    async def extract_metadata(self, pdf_path: str) -> Dict[str, str]:
        """
        Extract metadata from PDF.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Dictionary of metadata
        """
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                metadata = pdf_reader.metadata
                
                return {
                    'title': metadata.get('/Title', 'Unknown') if metadata else 'Unknown',
                    'author': metadata.get('/Author', 'Unknown') if metadata else 'Unknown',
                    'subject': metadata.get('/Subject', 'Unknown') if metadata else 'Unknown',
                    'creator': metadata.get('/Creator', 'Unknown') if metadata else 'Unknown',
                    'page_count': len(pdf_reader.pages)
                }
        except Exception as e:
            logger.error(f"Error extracting metadata: {e}")
            return {'error': str(e)}
    
    def save_uploaded_file(self, file_content: bytes, filename: str) -> str:
        """
        Save uploaded file to temporary directory.
        
        Args:
            file_content: Binary content of the file
            filename: Original filename
            
        Returns:
            Path to saved file
        """
        try:
            # Create temp directory if it doesn't exist
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, f"stormline_{filename}")
            
            with open(file_path, 'wb') as f:
                f.write(file_content)
            
            logger.info(f"File saved to: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"Error saving file: {e}")
            raise
    
    def cleanup_file(self, file_path: str):
        """
        Remove temporary file.
        
        Args:
            file_path: Path to file to remove
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            logger.warning(f"Error cleaning up file {file_path}: {e}")
