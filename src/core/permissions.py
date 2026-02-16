"""
RBAC Permission definitions for the AI Interviewer System.

Defines what each role can do and provides utilities for
checking permissions.
"""
from typing import List, Set

from src.models.auth import UserRole


# Permission constants
class Permissions:
    """All available permissions in the system."""
    
    # Admin
    ALL = "all"
    
    # Interview Management
    CREATE_INTERVIEW = "create_interview"
    VIEW_INTERVIEW = "view_interview"
    UPDATE_INTERVIEW = "update_interview"
    DELETE_INTERVIEW = "delete_interview"
    CONDUCT_INTERVIEW = "conduct_interview"
    
    # Session Management
    CREATE_SESSION = "create_session"
    VIEW_SESSION = "view_session"
    UPDATE_SESSION = "update_session"
    DELETE_SESSION = "delete_session"
    PARTICIPATE_SESSION = "participate_session"
    
    # Candidate Management
    CREATE_CANDIDATE = "create_candidate"
    VIEW_CANDIDATE = "view_candidate"
    UPDATE_CANDIDATE = "update_candidate"
    DELETE_CANDIDATE = "delete_candidate"
    
    # Document Management
    UPLOAD_DOCUMENT = "upload_document"
    VIEW_DOCUMENT = "view_document"
    DELETE_DOCUMENT = "delete_document"
    PARSE_DOCUMENT = "parse_document"
    
    # Question Bank
    VIEW_QUESTIONS = "view_questions"
    MANAGE_QUESTIONS = "manage_questions"
    
    # Reports
    VIEW_REPORTS = "view_reports"
    CREATE_REPORTS = "create_reports"
    EXPORT_REPORTS = "export_reports"
    
    # Voice/Audio
    USE_VOICE = "use_voice"
    
    # Analysis
    RUN_ANALYSIS = "run_analysis"
    VIEW_ANALYSIS = "view_analysis"


# Role to permissions mapping
ROLE_PERMISSIONS: dict[UserRole, List[str]] = {
    UserRole.ADMIN: [
        Permissions.ALL,  # Admin has all permissions
    ],
    
    UserRole.HIRING_MANAGER: [
        # Interview management
        Permissions.CREATE_INTERVIEW,
        Permissions.VIEW_INTERVIEW,
        Permissions.UPDATE_INTERVIEW,
        Permissions.DELETE_INTERVIEW,
        Permissions.CONDUCT_INTERVIEW,
        
        # Session management
        Permissions.CREATE_SESSION,
        Permissions.VIEW_SESSION,
        Permissions.UPDATE_SESSION,
        Permissions.DELETE_SESSION,
        Permissions.PARTICIPATE_SESSION,
        
        # Candidate management
        Permissions.CREATE_CANDIDATE,
        Permissions.VIEW_CANDIDATE,
        Permissions.UPDATE_CANDIDATE,
        Permissions.DELETE_CANDIDATE,
        
        # Document management
        Permissions.UPLOAD_DOCUMENT,
        Permissions.VIEW_DOCUMENT,
        Permissions.DELETE_DOCUMENT,
        Permissions.PARSE_DOCUMENT,
        
        # Question bank
        Permissions.VIEW_QUESTIONS,
        Permissions.MANAGE_QUESTIONS,
        
        # Reports
        Permissions.VIEW_REPORTS,
        Permissions.CREATE_REPORTS,
        Permissions.EXPORT_REPORTS,
        
        # Voice/Audio
        Permissions.USE_VOICE,
        
        # Analysis
        Permissions.RUN_ANALYSIS,
        Permissions.VIEW_ANALYSIS,
    ],
    
    UserRole.INTERVIEWER: [
        # Limited interview access
        Permissions.VIEW_INTERVIEW,
        Permissions.CONDUCT_INTERVIEW,
        
        # Session access
        Permissions.VIEW_SESSION,
        Permissions.UPDATE_SESSION,  # Can update during interview
        
        # View candidates
        Permissions.VIEW_CANDIDATE,
        
        # Document viewing
        Permissions.VIEW_DOCUMENT,
        
        # Question bank (view only)
        Permissions.VIEW_QUESTIONS,
        
        # Reports (view only)
        Permissions.VIEW_REPORTS,
        
        # Voice
        Permissions.USE_VOICE,
        
        # Analysis (view only)
        Permissions.VIEW_ANALYSIS,
    ],
    
    UserRole.CANDIDATE: [
        # Can only participate in their assigned session
        Permissions.PARTICIPATE_SESSION,
        Permissions.USE_VOICE,
    ],
}


def get_permissions_for_role(role: UserRole) -> List[str]:
    """
    Get the list of permissions for a given role.
    
    Args:
        role: The user role
        
    Returns:
        List of permission strings
    """
    return ROLE_PERMISSIONS.get(role, [])


def get_all_permissions_for_role(role: UserRole) -> Set[str]:
    """
    Get all permissions including inherited ones.
    
    Currently roles don't inherit from each other,
    but this function provides a hook for that.
    
    Args:
        role: The user role
        
    Returns:
        Set of all permission strings
    """
    permissions = set(get_permissions_for_role(role))
    
    # If admin, they have all permissions
    if Permissions.ALL in permissions:
        return {Permissions.ALL}
    
    return permissions


def has_permission(role: UserRole, permission: str, explicit_permissions: List[str] = None) -> bool:
    """
    Check if a role has a specific permission.
    
    Args:
        role: The user role
        permission: The permission to check
        explicit_permissions: Optional explicit permissions that override role-based
        
    Returns:
        True if the role has the permission
    """
    # Check explicit permissions first
    if explicit_permissions:
        if Permissions.ALL in explicit_permissions:
            return True
        return permission in explicit_permissions
    
    # Check role-based permissions
    role_permissions = get_permissions_for_role(role)
    
    if Permissions.ALL in role_permissions:
        return True
    
    return permission in role_permissions


def has_any_permission(role: UserRole, permissions: List[str], explicit_permissions: List[str] = None) -> bool:
    """
    Check if a role has any of the specified permissions.
    
    Args:
        role: The user role
        permissions: List of permissions to check
        explicit_permissions: Optional explicit permissions that override role-based
        
    Returns:
        True if the role has any of the permissions
    """
    return any(has_permission(role, p, explicit_permissions) for p in permissions)


def has_all_permissions(role: UserRole, permissions: List[str], explicit_permissions: List[str] = None) -> bool:
    """
    Check if a role has all of the specified permissions.
    
    Args:
        role: The user role
        permissions: List of permissions to check
        explicit_permissions: Optional explicit permissions that override role-based
        
    Returns:
        True if the role has all of the permissions
    """
    return all(has_permission(role, p, explicit_permissions) for p in permissions)


# Permission groups for convenience
INTERVIEW_MANAGEMENT_PERMISSIONS = [
    Permissions.CREATE_INTERVIEW,
    Permissions.VIEW_INTERVIEW,
    Permissions.UPDATE_INTERVIEW,
    Permissions.DELETE_INTERVIEW,
    Permissions.CONDUCT_INTERVIEW,
]

SESSION_MANAGEMENT_PERMISSIONS = [
    Permissions.CREATE_SESSION,
    Permissions.VIEW_SESSION,
    Permissions.UPDATE_SESSION,
    Permissions.DELETE_SESSION,
    Permissions.PARTICIPATE_SESSION,
]

DOCUMENT_MANAGEMENT_PERMISSIONS = [
    Permissions.UPLOAD_DOCUMENT,
    Permissions.VIEW_DOCUMENT,
    Permissions.DELETE_DOCUMENT,
    Permissions.PARSE_DOCUMENT,
]

REPORT_PERMISSIONS = [
    Permissions.VIEW_REPORTS,
    Permissions.CREATE_REPORTS,
    Permissions.EXPORT_REPORTS,
]
