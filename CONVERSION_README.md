# Edmund PDF to Stormline Master v3 Conversion Tool

## Overview

This tool converts Edmund job proposal PDFs (T18 Construction format) to the Stormline Master v3 proposal format. It extracts itemized data from the Edmund PDF and reformats it according to the Stormline Utilities, LLC standard proposal template.

## Features

- **Automatic Data Extraction**: Parses Edmund PDF proposals and extracts:
  - Project information (job name, date, city, address)
  - Storm drainage items
  - Water distribution items
  - Sanitary sewer items
  - Fire line/FDC items
  - Cost breakdown details

- **Multiple Output Formats**: Generates both:
  - **Text format** (`.txt`): Human-readable formatted proposal
  - **JSON format** (`.json`): Structured data for further processing

- **Stormline Master v3 Format**: Outputs match the official Stormline proposal template structure

## Requirements

- Python 3.7+
- PyMuPDF (fitz)

All dependencies are already included in the project's `requirements.txt`.

## Installation

The conversion script is ready to use. Just ensure you have the dependencies installed:

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

Simply run the conversion script from the project directory:

```bash
python3 convert_edmund_to_stormline.py
```

The script will:
1. Look for `workspacesstormlineutledmund.pdf` in the current directory
2. Extract all proposal data
3. Generate two output files:
   - `edmund_converted_to_stormline_v3.txt` (formatted text)
   - `edmund_converted_to_stormline_v3.json` (structured JSON)

### Example Output

```
Converting Edmund Job PDF to Stormline Master v3 format...
Input: workspacesstormlineutledmund.pdf

Extracting data from Edmund PDF...

Extracted Proposal Data:
  Job Name: Chick-fil-A
  Date: February 18, 2026
  City: Edmond
  Total: $569,900.00
  Storm Drain Items: 6
  Water Items: 7
  Sanitary Sewer Items: 5
  Fire Line Items: 5

Generating Stormline Master v3 format...
✓ Saved text output to: edmund_converted_to_stormline_v3.txt
✓ Saved JSON output to: edmund_converted_to_stormline_v3.json

================================================================================
CONVERSION COMPLETE!
================================================================================

Output files:
  - edmund_converted_to_stormline_v3.txt (formatted text)
  - edmund_converted_to_stormline_v3.json (structured data)
```

## Output Formats

### Text Format (`.txt`)

The text output is formatted to match the Stormline Master v3 template:

```
================================================================================
STORMLINE UTILITIES, LLC
PROPOSAL / BID SUBMITTAL
Storm · Water · Sewer · Fire / FDC
================================================================================

JOB NAME: Chick-fil-A
DATE: February 18, 2026
CITY: Edmond
ADDRESS: 4200 E Covell Road, Edmond, Oklahoma
GC / OWNER: T18 Construction
...

--------------------------------------------------------------------------------
STORM DRAIN
--------------------------------------------------------------------------------
#     DESCRIPTION                                   UNIT     QTY       
--------------------------------------------------------------------------------
1     18–24 Storm Pipe                              LF       420.00    
2     48 Storm Manhole                              EA       1.00      
...
```

### JSON Format (`.json`)

The JSON output provides structured data that can be used for further processing or integration with other systems:

```json
{
  "job_name": "Chick-fil-A",
  "date": "February 18, 2026",
  "city": "Edmond",
  "address": "4200 E Covell Road, Edmond, Oklahoma",
  "gc_owner": "T18 Construction",
  "sections": {
    "storm_drain": {
      "name": "STORM DRAIN",
      "items": [
        {
          "number": 1,
          "description": "18–24 Storm Pipe",
          "qty": 420.0,
          "unit": "LF",
          "unit_price": 0.0,
          "total": 0.0
        }
      ]
    }
  },
  "total_base_bid": 569900.0
}
```

## Data Mapping

The conversion tool maps Edmund PDF sections to Stormline Master v3 sections:

| Edmund Section | Stormline Section |
|----------------|-------------------|
| STORM DRAINAGE | STORM DRAIN |
| WATER DISTRIBUTION | WATER |
| SANITARY SEWER | SANITARY SEWER |
| FIRE LINE / FDC | FIRE LINE / FDC |

Each section preserves:
- Item number
- Description
- Quantity
- Unit of measurement (LF, EA, LS, etc.)

## Limitations

- The Edmund PDF must follow the T18 Construction format
- Unit prices are not extracted (set to $0.00 in output)
- Individual line item totals are not calculated
- The script assumes each field is on a separate line in the PDF

## Troubleshooting

### "Input file not found" Error

Make sure `workspacesstormlineutledmund.pdf` is in the same directory as the script, or update the `input_pdf` variable in the script to point to your PDF file.

### No Items Extracted

If items are not being extracted:
1. Verify the PDF follows the Edmund/T18 Construction format
2. Check that the PDF is text-based (not scanned images)
3. Review the section headers match expected names

### Missing Data

If some data is missing:
- Check the PDF structure matches the expected format
- Review extraction patterns in the `extract_section_items()` function
- The PDF may have formatting variations that need custom handling

## Customization

To convert a different PDF or customize the conversion:

1. **Change Input File**: Update `input_pdf` in the `main()` function
2. **Add Custom Parsing**: Modify `extract_section_items()` for different PDF formats
3. **Adjust Output Format**: Update `format_stormline_output()` to change the text output

## Integration

The JSON output can be easily integrated with:
- Database systems
- Spreadsheet applications
- Web applications
- Reporting tools
- PlanSwift or other construction software

Example Python usage:

```python
import json

# Load the converted data
with open('edmund_converted_to_stormline_v3.json', 'r') as f:
    proposal_data = json.load(f)

# Access data
job_name = proposal_data['job_name']
storm_items = proposal_data['sections']['storm_drain']['items']
total = proposal_data['total_base_bid']

# Process as needed
for item in storm_items:
    print(f"{item['description']}: {item['qty']} {item['unit']}")
```

## Support

For issues or questions:
- Review the main [README.md](README.md)
- Check [GitHub Issues](https://github.com/tigertcorey/stormlineutl/issues)

## License

This tool is part of the Stormline UTL project and follows the same license terms.
