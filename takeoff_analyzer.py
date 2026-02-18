"""
Takeoff analyzer module for Stormline UTL Bot.
Analyzes construction plans for storm, water, sewer, and FDC systems using AI.
"""

import logging
import re
from typing import Dict, List, Optional, Any
from ai_models import MultiModelOrchestrator

logger = logging.getLogger(__name__)


class TakeoffAnalyzer:
    """Analyzes construction plans and performs quantity takeoff."""
    
    # System types we're analyzing
    SYSTEM_TYPES = ['storm', 'water', 'sewer', 'fdc']
    
    # Maximum text length for AI analysis (to stay within token limits)
    MAX_AI_TEXT_LENGTH = 8000
    
    # Common units and patterns
    PIPE_PATTERNS = [
        r'(\d+)["\']?\s*(?:inch|in)?\s*(?:pipe|line)',
        r'(\d+)\s*(?:LF|L\.F\.|linear\s*feet|lineal\s*feet)',
        r'(\d+)\s*(?:diameter|dia\.?|Ø)',
    ]
    
    def __init__(self):
        """Initialize takeoff analyzer."""
        self.orchestrator = MultiModelOrchestrator()
        logger.info("Takeoff analyzer initialized")
    
    async def analyze_plans(
        self,
        pdf_text: str,
        pdf_metadata: Dict[str, str],
        systems: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Analyze construction plans and perform takeoff.
        
        Args:
            pdf_text: Extracted text from PDF
            pdf_metadata: PDF metadata
            systems: List of systems to analyze (defaults to all)
            
        Returns:
            Dictionary containing takeoff analysis
        """
        if systems is None:
            systems = self.SYSTEM_TYPES
        
        try:
            logger.info(f"Analyzing plans for systems: {', '.join(systems)}")
            
            # Preliminary text analysis
            text_analysis = self._analyze_text_patterns(pdf_text, systems)
            
            # AI-powered analysis
            ai_analysis = await self._ai_analyze_plans(pdf_text, pdf_metadata, systems)
            
            # Combine results
            result = {
                'project_info': {
                    'title': pdf_metadata.get('title', 'Unknown Project'),
                    'page_count': pdf_metadata.get('page_count', 0),
                },
                'systems_analyzed': systems,
                'text_patterns': text_analysis,
                'ai_analysis': ai_analysis,
                'summary': self._generate_summary(text_analysis, ai_analysis)
            }
            
            logger.info("Plan analysis completed successfully")
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing plans: {e}")
            raise
    
    def _analyze_text_patterns(self, text: str, systems: List[str]) -> Dict[str, List]:
        """
        Analyze text patterns for construction elements.
        
        Args:
            text: Extracted PDF text
            systems: Systems to analyze
            
        Returns:
            Dictionary of found patterns
        """
        patterns = {}
        
        for system in systems:
            patterns[system] = {
                'mentions': [],
                'measurements': [],
                'materials': []
            }
            
            # Find system mentions
            system_pattern = re.compile(rf'\b{system}\b', re.IGNORECASE)
            mentions = system_pattern.findall(text)
            patterns[system]['mentions'] = len(mentions)
            
            # Find pipe sizes
            for pipe_pattern in self.PIPE_PATTERNS:
                matches = re.findall(pipe_pattern, text, re.IGNORECASE)
                patterns[system]['measurements'].extend(matches)
            
            # Find material mentions
            materials = ['PVC', 'HDPE', 'concrete', 'ductile iron', 'steel', 'copper']
            for material in materials:
                if re.search(rf'\b{material}\b', text, re.IGNORECASE):
                    patterns[system]['materials'].append(material)
        
        return patterns
    
    async def _ai_analyze_plans(
        self,
        pdf_text: str,
        pdf_metadata: Dict[str, str],
        systems: List[str]
    ) -> str:
        """
        Use AI to analyze construction plans.
        
        Args:
            pdf_text: Extracted PDF text
            pdf_metadata: PDF metadata
            systems: Systems to analyze
            
        Returns:
            AI analysis text
        """
        # Truncate text if too long (to stay within token limits)
        if len(pdf_text) > self.MAX_AI_TEXT_LENGTH:
            pdf_text = pdf_text[:self.MAX_AI_TEXT_LENGTH] + "\n... [text truncated]"
        
        prompt = f"""You are a construction takeoff specialist analyzing construction plans. 
Please analyze the following construction plan document and provide a detailed takeoff for these systems: {', '.join(systems)}.

Project Information:
- Title: {pdf_metadata.get('title', 'Unknown')}
- Pages: {pdf_metadata.get('page_count', 'Unknown')}

Document Content:
{pdf_text}

Please provide a comprehensive takeoff analysis including:

1. **Storm System** (if applicable):
   - Pipe sizes and linear footage
   - Catch basins and inlets
   - Manholes
   - Materials specified

2. **Water System** (if applicable):
   - Water line sizes and lengths
   - Fire hydrants
   - Valves and fittings
   - Materials specified

3. **Sewer System** (if applicable):
   - Sewer line sizes and lengths
   - Manholes
   - Cleanouts
   - Materials specified

4. **FDC (Fire Department Connection)** (if applicable):
   - Location and specifications
   - Connected systems
   - Materials and accessories

5. **Quantities Summary**:
   - Major materials and quantities
   - Labor considerations
   - Special notes or requirements

Format your response clearly with sections and bullet points for easy reading."""
        
        try:
            # Use Claude for analysis (construction/technical analysis)
            analysis = await self.orchestrator.query_claude(prompt)
            return analysis
            
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return f"AI analysis unavailable: {str(e)}"
    
    def _generate_summary(
        self,
        text_patterns: Dict[str, Any],
        ai_analysis: str
    ) -> str:
        """
        Generate a summary of the takeoff analysis.
        
        Args:
            text_patterns: Pattern analysis results
            ai_analysis: AI analysis results
            
        Returns:
            Summary text
        """
        summary_lines = ["📊 **Takeoff Summary**\n"]
        
        # Add pattern analysis summary
        for system, data in text_patterns.items():
            mentions = data.get('mentions', 0)
            if mentions > 0:
                summary_lines.append(
                    f"- **{system.upper()}**: {mentions} references found"
                )
                if data.get('materials'):
                    summary_lines.append(
                        f"  Materials: {', '.join(set(data['materials']))}"
                    )
        
        return '\n'.join(summary_lines)
    
    def format_takeoff_response(self, analysis: Dict[str, Any]) -> str:
        """
        Format takeoff analysis for Telegram response.
        
        Args:
            analysis: Analysis results dictionary
            
        Returns:
            Formatted response text
        """
        response = f"""📋 **Construction Takeoff Analysis**

**Project:** {analysis['project_info']['title']}
**Pages Analyzed:** {analysis['project_info']['page_count']}
**Systems:** {', '.join([s.upper() for s in analysis['systems_analyzed']])}

{analysis['summary']}

---

**Detailed Analysis:**

{analysis['ai_analysis']}

---

💡 **Note:** This automated takeoff should be verified by a qualified professional. Please review all quantities and specifications against the original plans.
"""
        return response
