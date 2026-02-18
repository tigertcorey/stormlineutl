#!/usr/bin/env python3
"""
Convert Edmund Job PDF to Stormline Master v3 Format
Extracts itemized data from Edmund PDF and formats it into Stormline Master v3 structure.
"""

import fitz  # PyMuPDF
import re
import sys
import json
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class LineItem:
    """Represents a single line item in the proposal."""
    number: int
    description: str
    qty: float
    unit: str
    unit_price: float = 0.0
    total: float = 0.0


@dataclass
class Section:
    """Represents a section of the proposal (Storm, Water, Sewer, Fire)."""
    name: str
    items: List[LineItem]
    subtotal: float = 0.0


@dataclass
class Proposal:
    """Complete proposal structure."""
    job_name: str
    date: str
    city: str
    address: str
    gc_owner: str = ""
    civil_engineer: str = ""
    engineers_date: str = ""
    storm_drain: Section = None
    water: Section = None
    sanitary_sewer: Section = None
    fire_line: Section = None
    total_base_bid: float = 0.0
    cost_breakdown: Dict[str, float] = None


def extract_edmund_data(pdf_path: str) -> Proposal:
    """
    Extract data from Edmund PDF format.
    
    Args:
        pdf_path: Path to the Edmund PDF file
        
    Returns:
        Proposal object with extracted data
    """
    pdf = fitz.open(pdf_path)
    
    # Extract text from all pages
    full_text = ""
    for page in pdf:
        full_text += page.get_text()
    
    pdf.close()
    
    # Extract project information
    job_match = re.search(r'Project:\s*(.+)', full_text)
    address_match = re.search(r'Address:\s*(.+)', full_text)
    date_match = re.search(r'Date:\s*(.+)', full_text)
    
    job_name = job_match.group(1).strip() if job_match else "Unknown Project"
    address = address_match.group(1).strip() if address_match else ""
    date = date_match.group(1).strip() if date_match else ""
    
    # Extract city from address (e.g., "4200 E Covell Road, Edmond, Oklahoma")
    city = ""
    if address:
        parts = address.split(',')
        if len(parts) >= 2:
            city = parts[1].strip()
    
    # Extract sections
    storm_items = extract_section_items(full_text, "STORM DRAINAGE")
    water_items = extract_section_items(full_text, "WATER DISTRIBUTION")
    sewer_items = extract_section_items(full_text, "SANITARY SEWER")
    fire_items = extract_section_items(full_text, "FIRE LINE / FDC")
    
    # Extract cost breakdown
    cost_breakdown = extract_cost_breakdown(full_text)
    
    # Calculate total
    total_match = re.search(r'TOTAL PROPOSAL AMOUNT\s+\$([0-9,]+)', full_text)
    total = float(total_match.group(1).replace(',', '')) if total_match else 0.0
    
    # Create proposal
    proposal = Proposal(
        job_name=job_name,
        date=date,
        city=city,
        address=address,
        gc_owner="T18 Construction",
        storm_drain=Section("STORM DRAIN", storm_items),
        water=Section("WATER", water_items),
        sanitary_sewer=Section("SANITARY SEWER", sewer_items),
        fire_line=Section("FIRE LINE / FDC", fire_items),
        total_base_bid=total,
        cost_breakdown=cost_breakdown
    )
    
    return proposal


def extract_section_items(text: str, section_name: str) -> List[LineItem]:
    """
    Extract line items from a specific section.
    
    Args:
        text: Full text from PDF
        section_name: Name of the section to extract
        
    Returns:
        List of LineItem objects
    """
    items = []
    
    # Find the section - in Edmund PDFs, each field is on a separate line
    lines = text.split('\n')
    
    # Find the start of this section
    in_section = False
    section_lines = []
    
    for line in lines:
        if section_name in line:
            in_section = True
            continue
        
        if in_section:
            # Check if we hit the next section
            next_sections = ['SANITARY SEWER', 'WATER DISTRIBUTION', 'FIRE LINE', 'COST BREAKDOWN']
            if any(sec in line for sec in next_sections) and section_name not in line:
                break
            section_lines.append(line.strip())
    
    if not section_lines:
        return items
    
    # Skip header lines (Item, Description, Qty, Unit)
    i = 0
    while i < len(section_lines) and section_lines[i] in ['Item', 'Description', 'Qty', 'Unit', '']:
        i += 1
    
    # Parse items in groups of 4 lines: number, description, qty, unit
    while i < len(section_lines):
        # Skip empty lines
        if not section_lines[i]:
            i += 1
            continue
        
        # Try to parse as item number
        if i + 3 < len(section_lines):
            try:
                item_num_str = section_lines[i]
                description = section_lines[i + 1]
                qty_str = section_lines[i + 2]
                unit = section_lines[i + 3]
                
                # Validate and parse
                if item_num_str.isdigit() and unit and len(unit) <= 10:
                    item_num = int(item_num_str)
                    
                    # Parse quantity - could be "Included" or a number
                    if qty_str.lower() == 'included':
                        qty = 1.0
                    else:
                        qty = float(qty_str.replace(',', ''))
                    
                    items.append(LineItem(
                        number=item_num,
                        description=description,
                        qty=qty,
                        unit=unit
                    ))
                    
                    i += 4
                    continue
            except (ValueError, IndexError):
                pass
        
        i += 1
    
    return items


def extract_cost_breakdown(text: str) -> Dict[str, float]:
    """
    Extract cost breakdown section.
    
    Args:
        text: Full text from PDF
        
    Returns:
        Dictionary with cost categories and amounts
    """
    breakdown = {}
    
    # Find cost breakdown section
    section_match = re.search(r'COST BREAKDOWN(.+?)TOTAL PROPOSAL:', text, re.DOTALL)
    if not section_match:
        return breakdown
    
    section_text = section_match.group(1)
    
    # Extract cost items
    patterns = [
        (r'Materials.*?\$([0-9,]+)', 'Materials'),
        (r'Labor\s+\$([0-9,]+)', 'Labor'),
        (r'Equipment\s+\$([0-9,]+)', 'Equipment'),
        (r'Travel / Lodging\s+\$([0-9,]+)', 'Travel'),
        (r'Subtotal Field Cost\s+\$([0-9,]+)', 'Subtotal Field Cost'),
        (r'Overhead & Profit.*?\$([0-9,]+)', 'Overhead & Profit'),
    ]
    
    for pattern, key in patterns:
        match = re.search(pattern, section_text, re.IGNORECASE)
        if match:
            breakdown[key] = float(match.group(1).replace(',', ''))
    
    return breakdown


def format_stormline_output(proposal: Proposal) -> str:
    """
    Format proposal data into Stormline Master v3 text format.
    
    Args:
        proposal: Proposal object with extracted data
        
    Returns:
        Formatted text string
    """
    output = []
    
    # Header
    output.append("=" * 80)
    output.append("STORMLINE UTILITIES, LLC")
    output.append("PROPOSAL / BID SUBMITTAL")
    output.append("Storm · Water · Sewer · Fire / FDC")
    output.append("=" * 80)
    output.append("")
    
    # Project information
    output.append(f"JOB NAME: {proposal.job_name}")
    output.append(f"DATE: {proposal.date}")
    output.append(f"CITY: {proposal.city}")
    output.append(f"ADDRESS: {proposal.address}")
    output.append(f"GC / OWNER: {proposal.gc_owner}")
    output.append(f"CIVIL ENGINEER: {proposal.civil_engineer}")
    output.append(f"ENGINEER'S DATE: {proposal.engineers_date}")
    output.append("")
    
    # Format each section
    sections = [
        proposal.storm_drain,
        proposal.water,
        proposal.sanitary_sewer,
        proposal.fire_line
    ]
    
    section_totals = []
    
    for section in sections:
        if section and section.items:
            output.append("-" * 80)
            output.append(f"{section.name}")
            output.append("-" * 80)
            output.append(f"{'#':<5} {'DESCRIPTION':<45} {'UNIT':<8} {'QTY':<10}")
            output.append("-" * 80)
            
            section_total = 0.0
            for item in section.items:
                output.append(
                    f"{item.number:<5} {item.description:<45} {item.unit:<8} {item.qty:<10.2f}"
                )
                section_total += item.total
            
            output.append("-" * 80)
            output.append(f"{section.name} SUBTOTAL: ${section_total:,.2f}")
            output.append("")
            section_totals.append(section_total)
    
    # Total
    output.append("=" * 80)
    output.append(f"TOTAL BASE BID: ${proposal.total_base_bid:,.2f}")
    output.append("=" * 80)
    output.append("")
    
    # Cost breakdown if available
    if proposal.cost_breakdown:
        output.append("-" * 80)
        output.append("COST BREAKDOWN")
        output.append("-" * 80)
        for key, value in proposal.cost_breakdown.items():
            output.append(f"{key:<40} ${value:,.2f}")
        output.append("")
    
    return "\n".join(output)


def save_as_json(proposal: Proposal, output_path: str):
    """
    Save proposal data as JSON.
    
    Args:
        proposal: Proposal object
        output_path: Path to save JSON file
    """
    # Convert to dictionary
    data = {
        'job_name': proposal.job_name,
        'date': proposal.date,
        'city': proposal.city,
        'address': proposal.address,
        'gc_owner': proposal.gc_owner,
        'civil_engineer': proposal.civil_engineer,
        'engineers_date': proposal.engineers_date,
        'sections': {},
        'total_base_bid': proposal.total_base_bid,
        'cost_breakdown': proposal.cost_breakdown
    }
    
    # Add sections
    for section_name, section in [
        ('storm_drain', proposal.storm_drain),
        ('water', proposal.water),
        ('sanitary_sewer', proposal.sanitary_sewer),
        ('fire_line', proposal.fire_line)
    ]:
        if section and section.items:
            data['sections'][section_name] = {
                'name': section.name,
                'items': [
                    {
                        'number': item.number,
                        'description': item.description,
                        'qty': item.qty,
                        'unit': item.unit,
                        'unit_price': item.unit_price,
                        'total': item.total
                    }
                    for item in section.items
                ],
                'subtotal': section.subtotal
            }
    
    # Write JSON
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)


def main():
    """Main conversion function."""
    # Input and output paths
    input_pdf = "workspacesstormlineutledmund.pdf"
    output_txt = "edmund_converted_to_stormline_v3.txt"
    output_json = "edmund_converted_to_stormline_v3.json"
    
    # Check if input exists
    if not Path(input_pdf).exists():
        print(f"Error: Input file '{input_pdf}' not found!")
        sys.exit(1)
    
    print("Converting Edmund Job PDF to Stormline Master v3 format...")
    print(f"Input: {input_pdf}")
    
    try:
        # Extract data
        print("\nExtracting data from Edmund PDF...")
        proposal = extract_edmund_data(input_pdf)
        
        # Display summary
        print(f"\nExtracted Proposal Data:")
        print(f"  Job Name: {proposal.job_name}")
        print(f"  Date: {proposal.date}")
        print(f"  City: {proposal.city}")
        print(f"  Total: ${proposal.total_base_bid:,.2f}")
        
        if proposal.storm_drain:
            print(f"  Storm Drain Items: {len(proposal.storm_drain.items)}")
        if proposal.water:
            print(f"  Water Items: {len(proposal.water.items)}")
        if proposal.sanitary_sewer:
            print(f"  Sanitary Sewer Items: {len(proposal.sanitary_sewer.items)}")
        if proposal.fire_line:
            print(f"  Fire Line Items: {len(proposal.fire_line.items)}")
        
        # Format and save text output
        print(f"\nGenerating Stormline Master v3 format...")
        formatted_output = format_stormline_output(proposal)
        
        with open(output_txt, 'w') as f:
            f.write(formatted_output)
        print(f"✓ Saved text output to: {output_txt}")
        
        # Save JSON output
        save_as_json(proposal, output_json)
        print(f"✓ Saved JSON output to: {output_json}")
        
        print("\n" + "=" * 80)
        print("CONVERSION COMPLETE!")
        print("=" * 80)
        print(f"\nOutput files:")
        print(f"  - {output_txt} (formatted text)")
        print(f"  - {output_json} (structured data)")
        
    except Exception as e:
        print(f"\nError during conversion: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
