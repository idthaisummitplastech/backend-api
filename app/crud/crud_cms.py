from typing import Any, Dict, List, Optional, Type
from sqlalchemy.orm import Session
from app.crud.base import CRUDBase
from app.db.base_class import Base
from app.models.cms import (
    SiteSetting,
    NavMenu,
    HeroSection,
    Announcement,
    Partner,
    Feature,
    Service,
    Product,
    BlogPost,
    Testimonial,
    Faq,
    Statistic,
    ContactSubmission,
    Certification,
    Facility,
    SustainabilityReport,
)
from app.models.auth import User


class CMSModelRegistry:
    """
    Central dynamic model registry mapping URL slugs to ORM models.
    Enables zero-boilerplate, generic CRUD operations for Web Perusahaan CMS.
    """

    _MODELS: Dict[str, Type[Base]] = {
        "settings": SiteSetting,
        "nav-menus": NavMenu,
        "hero-sections": HeroSection,
        "announcements": Announcement,
        "partners": Partner,
        "features": Feature,
        "services": Service,
        "products": Product,
        "blog-posts": BlogPost,
        "testimonials": Testimonial,
        "faqs": Faq,
        "statistics": Statistic,
        "contacts": ContactSubmission,
        "certifications": Certification,
        "facilities": Facility,
        "sustainability-reports": SustainabilityReport,
        "users": User,
    }


    @classmethod
    def get_model(cls, slug: str) -> Optional[Type[Base]]:
        return cls._MODELS.get(slug.lower())

    @classmethod
    def get_crud(cls, slug: str) -> Optional[CRUDBase]:
        model = cls.get_model(slug)
        if not model:
            return None
        return CRUDBase(model)


class CRUDContact(CRUDBase[ContactSubmission, Any, Any]):
    """Specialized contact inquiries repository."""
    def get_unread(self, db: Session) -> List[ContactSubmission]:
        return db.query(self.model).filter(self.model.is_read == False).order_by(self.model.created_at.desc()).all()


crud_contact = CRUDContact(ContactSubmission)
