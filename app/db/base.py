# Import all the models, so that Base has them before being imported by Alembic or runtime
from app.db.base_class import Base  # noqa
from app.models.auth import RecruitmentAdmin, User  # noqa
from app.models.recruitment import (  # noqa
    JobPosting,
    Applicant,
    InterviewSchedule,
    TestQuestion,
    TestSubmission,
    KaryawanSementara,
    RecruitmentSetting,
)
from app.models.cms import (  # noqa
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
)
