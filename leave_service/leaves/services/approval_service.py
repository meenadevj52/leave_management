import logging
from typing import List, Dict, Optional
from uuid import UUID
from .employee_service import EmployeeServiceClient
from ..utils import to_uuid

logger = logging.getLogger(__name__)


class ApprovalChainService:
    ROLE_MAPPING = {
        'REPORTING_MANAGER': 'Reporting Manager',
        'HR_MANAGER': 'HR_MANAGER',
        'HR': 'HR',
        'CHRO': 'CHRO',
        'DEPARTMENT_HEAD': 'Department Head',
        'CFO': 'CFO',
        'CEO': 'CEO',
        'ADMIN': 'ADMIN',
        'TECHNOLOGY_MANAGER': 'TECHNOLOGY_MANAGER',
        'MANAGER': 'MANAGER'
    }
    
    @staticmethod
    def build_approval_chain(
        tenant_id: UUID,
        employee_data: Dict,
        approval_route: List[str]
    ) -> List[Dict]:

        if not approval_route:
            logger.warning("No approval route provided in policy")
            return []
        
        approval_chain = []
        
        logger.info(f"Building approval chain for roles: {approval_route}")
        
        for idx, role in enumerate(approval_route):
            approver = ApprovalChainService._get_approver_for_role(
                tenant_id, role, employee_data
            )
            
            if approver:
                approval_chain.append({
                    'step': idx,
                    'role': role,
                    'user_id': str(approver['id']),
                    'approver_name': approver.get('full_name', approver.get('email')),
                    'approver_email': approver.get('email')
                })
                logger.info(f"Step {idx}: {role} → {approver.get('full_name')} ({approver.get('email')})")
            else:
                logger.warning(f"Step {idx}: No approver found for role {role}")
                approval_chain.append({
                    'step': idx,
                    'role': role,
                    'user_id': None,
                    'approver_name': f'{role} (Not Assigned)',
                    'approver_email': None
                })
        
        return approval_chain
    
    @staticmethod
    def _get_approver_for_role(
        tenant_id: UUID,
        role: str,
        employee_data: Dict
    ) -> Optional[Dict]:

        try:
            if role == 'REPORTING_MANAGER':
                manager_id = employee_data.get('manager_id')
                if manager_id:
                    logger.info(f"Fetching REPORTING_MANAGER with ID: {manager_id}")
                    return EmployeeServiceClient.get_employee_details(str(manager_id))
                else:
                    logger.warning(f"No manager_id found in employee data")
                return None
            
            elif role == 'DEPARTMENT_HEAD':
                department = employee_data.get('department')
                if department:
                    logger.info(f"Fetching DEPARTMENT_HEAD for department: {department}")
                    return EmployeeServiceClient.get_department_head(tenant_id, department)
                else:
                    logger.warning(f"No department found in employee data")
                return None
            
            elif role in ['HR_MANAGER', 'HR', 'CHRO', 'CFO', 'CEO', 'ADMIN', 'TECHNOLOGY_MANAGER', 'MANAGER']:
                logger.info(f"    Fetching user with role: {role}")
                users = EmployeeServiceClient.get_users_by_role(tenant_id, role)
                
                if users:
                    logger.info(f"Found {len(users)} user(s) with role {role}")
                    return users[0]
                else:
                    logger.warning(f"No users found with role {role}")
                return None
            
            else:
                logger.warning(f"Unknown approval role: {role}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting approver for role {role}: {str(e)}", exc_info=True)
            return None
    
    @staticmethod
    def validate_approval_chain(approval_chain: List[Dict]) -> bool:
        if not approval_chain:
            logger.error("Approval chain is empty")
            return False
        
        has_valid_approver = any(
            step.get('user_id') is not None 
            for step in approval_chain
        )
        
        if not has_valid_approver:
            logger.error("No valid approvers found in approval chain")
        
        return has_valid_approver