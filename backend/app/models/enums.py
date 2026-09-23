from enum import Enum


class UserRole(str, Enum):
    JOB_SEEKER = "job_seeker"
    EMPLOYER = "employer"
    ADMIN = "admin"


class ProficiencyLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class EmploymentType(str, Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    TEMPORARY = "temporary"


class ExperienceLevel(str, Enum):
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    EXECUTIVE = "executive"


class JobStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"
    ARCHIVED = "archived"


class ApplicationStatus(str, Enum):
    APPLIED = "applied"
    VIEWED = "viewed"
    SHORTLISTED = "shortlisted"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"
    SAVED = "saved"


class InteractionType(str, Enum):
    VIEW = "view"
    SAVE = "save"
    APPLY = "apply"
    DISMISS = "dismiss"
    IGNORE = "ignore"
    CLICK = "click"


class WorkMode(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"


class FeedbackReason(str, Enum):
    RELEVANT = "relevant"
    NOT_RELEVANT = "not_relevant"
    ALREADY_APPLIED = "already_applied"
    NOT_INTERESTED = "not_interested"
    TOO_DIFFICULT = "too_difficult"
    LOCATION_ISSUE = "location_issue"
    SALARY_ISSUE = "salary_issue"
    OTHER = "other"


class SkillEdgeType(str, Enum):
    PREREQ = "prereq"
    TRANSFER = "transfer"
    SUPERSEDES = "supersedes"


class PathStepKind(str, Enum):
    SKILL = "skill"
    PROJECT = "project"
    CERT = "cert"


class PathStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class SkillSource(str, Enum):
    MANUAL = "manual"
    RESUME = "resume"
