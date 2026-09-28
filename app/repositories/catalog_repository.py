import os
import pandas as pd
from typing import List, Dict, Optional
from app.core.logging import get_logger

logger = get_logger(__name__)

class CatalogRepository:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.courses_df = None
        self.agenda_df = None
        self._load_data()

    def _load_data(self):
        courses_path = os.path.join(self.data_dir, "courses_catalog.xlsx")
        agenda_path = os.path.join(self.data_dir, "agenda.xlsx")
        
        try:
            if os.path.exists(courses_path):
                self.courses_df = pd.read_excel(courses_path)
            else:
                logger.warning(f"Courses catalog not found at {courses_path}")
                
            if os.path.exists(agenda_path):
                self.agenda_df = pd.read_excel(agenda_path)
            else:
                logger.warning(f"Agenda not found at {agenda_path}")
        except Exception as e:
            logger.error(f"Error loading catalog data: {e}")

    def get_all_courses(self) -> List[Dict]:
        if self.courses_df is None:
            return []
        return self.courses_df.to_dict('records')

    def get_course_agenda(self, course_title: str) -> Optional[Dict]:
        """Find the next session details for a given course title. Matches loosely."""
        if self.agenda_df is None or pd.isna(course_title) or not course_title:
            return None
            
        course_title_lower = str(course_title).lower()
        # Find partial match
        match = self.agenda_df[self.agenda_df["Course Title"].astype(str).str.lower().str.contains(course_title_lower, na=False)]
        
        if not match.empty:
            return match.iloc[0].to_dict()
        return None

    def get_course_details(self, course_title: str) -> Optional[Dict]:
        """Find the course details for a given course title. Matches loosely."""
        if self.courses_df is None or pd.isna(course_title) or not course_title:
            return None
            
        course_title_lower = str(course_title).lower()
        match = self.courses_df[self.courses_df["Course Title"].astype(str).str.lower().str.contains(course_title_lower, na=False)]
        
        if not match.empty:
            return match.iloc[0].to_dict()
        return None

    def get_catalog_content_text(self) -> str:
        """Format the entire catalog into a text blob for LLM prompts."""
        if self.courses_df is None:
            return "Catalogue non disponible."
            
        lines = []
        for idx, row in self.courses_df.iterrows():
            lines.append(f"- {row.get('Course Title')} ({row.get('Hours')}): {row.get('Short Description')} [Outils: {row.get('Tools Used')}]")
        return "\n".join(lines)
