import re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple


class RuleParser:

    OPERATORS = {
        'eq': lambda a, b: a == b,
        'neq': lambda a, b: a != b,
        'gt': lambda a, b: a > b,
        'gte': lambda a, b: a >= b,
        'lt': lambda a, b: a < b,
        'lte': lambda a, b: a <= b,
        'in': lambda a, b: a in b,
        'not_in': lambda a, b: a not in b,
        'contains': lambda a, b: b in a,
        'startswith': lambda a, b: str(a).startswith(str(b)),
        'endswith': lambda a, b: str(a).endswith(str(b)),
    }

    @staticmethod
    def resolve_dynamic_value(value: Any, context: Dict[str, Any]) -> Any:

        if isinstance(value, str) and value.startswith('{') and value.endswith('}'):
            key = value[1:-1]
            return context.get(key, value)
        return value

    @staticmethod
    def evaluate_check(check: Dict[str, Any], context: Dict[str, Any]) -> bool:
    
        field = check.get('field')
        operator = check.get('operator')
        expected_value = check.get('value')

        actual_value = context.get(field)

        expected_value = RuleParser.resolve_dynamic_value(expected_value, context)

        op_func = RuleParser.OPERATORS.get(operator)
        if not op_func:
            raise ValueError(f"Unknown operator: {operator}")

        try:
            return op_func(actual_value, expected_value)
        except (TypeError, ValueError) as e:
            print(f"Check evaluation error: {e}")
            return False

    @staticmethod
    def evaluate_condition(condition: Dict[str, Any], context: Dict[str, Any]) -> bool:

        checks = condition.get('checks', [])

        if not checks:
            return True

        for check in checks:
            if not RuleParser.evaluate_check(check, context):
                return False

        return True

    @staticmethod
    def validate_leave_request(
        policy: 'Policy',
        request_data: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:

        full_context = {**context, **request_data}

        errors = []
        actions_to_execute = []

        for condition in policy.conditions:
            if RuleParser.evaluate_condition(condition, full_context):

                action = condition.get('action_if_true', {})
                action_type = action.get('type')

                if action_type == 'reject_request':

                    reason = action.get('params', {}).get('reason', 'Policy violation')
                    errors.append({
                        'condition_id': condition.get('id'),
                        'description': condition.get('description'),
                        'reason': reason,
                        'action': action
                    })
                elif action_type in ['require_documentation', 'require_fitness_certificate', 
                                     'adjust_leave_days', 'require_additional_approval', 
                                     'adjust_carry_forward', 'expire_balance']:

                    actions_to_execute.append({
                        'type': action_type,
                        'params': action.get('params', {}),
                        'condition_id': condition.get('id')
                    })
                elif action_type in ['allow_request', 'set_entitlement', 'add_entitlement']:

                    actions_to_execute.append({
                        'type': action_type,
                        'params': action.get('params', {}),
                        'condition_id': condition.get('id')
                    })

        is_valid = len(errors) == 0

        return is_valid, errors, actions_to_execute

    @staticmethod
    def get_approval_chain(policy: 'Policy', employee: Dict[str, Any]) -> List[Dict[str, Any]]:

        approval_chain = []

        for step, role in enumerate(policy.approval_route):
            approver = {'step': step, 'role': role, 'user_id': None}

            if role == 'REPORTING_MANAGER':
                approver['user_id'] = employee.get('manager_id')
            elif role == 'DEPARTMENT_HEAD':
                approver['user_id'] = employee.get('department_head_id')
            elif role in ['HR_MANAGER', 'CHRO', 'HR', 'ADMIN', 'CFO']:
                approver['user_id'] = None
            else:
                approver['user_id'] = None

            approval_chain.append(approver)

        return approval_chain

    @staticmethod
    def check_policy_eligibility(
        policy: 'Policy',
        employee: Dict[str, Any]
    ) -> Tuple[bool, str]:
        employee_role = employee.get('role')
        employee_dept = employee.get('department')
        employee_type = employee.get('employment_type')

        if employee_role in policy.excludes:
            return False, f"Employee role '{employee_role}' is excluded from this policy."

        if employee_dept in policy.excludes:
            return False, f"Employee department '{employee_dept}' is excluded from this policy."

        if policy.applies_to:
            if employee_role not in policy.applies_to and employee_dept not in policy.applies_to:
                return False, f"This policy does not apply to '{employee_role}' or '{employee_dept}'."

        if policy.entitlement:
            allowed_types = policy.entitlement.get('employment_types', [])
            if allowed_types and employee_type not in allowed_types:
                return False, f"This policy does not apply to employment type '{employee_type}'."

        return True, "Policy applies to this employee."


class ActionExecutor:

    @staticmethod
    def execute_require_documentation(params: Dict[str, Any], leave_request: Dict[str, Any]) -> Dict[str, Any]:
        leave_request['documentation_required'] = True
        leave_request['required_doc_type'] = params.get('doc_type', 'General')
        leave_request['doc_threshold'] = params.get('threshold', 0)
        return leave_request

    @staticmethod
    def execute_require_fitness_certificate(params: Dict[str, Any], leave_request: Dict[str, Any]) -> Dict[str, Any]:
        leave_request['fitness_certificate_required'] = True
        leave_request['fitness_cert_threshold'] = params.get('threshold', 14)
        return leave_request

    @staticmethod
    def execute_adjust_leave_days(params: Dict[str, Any], leave_request: Dict[str, Any]) -> Dict[str, Any]:
        if params.get('exclude_holidays'):
            original_days = leave_request.get('leave_days', 0)
            holidays_count = leave_request.get('holidays_in_range', 0)
            adjusted_days = max(0, original_days - holidays_count)
            leave_request['leave_days'] = adjusted_days
            leave_request['adjustment_reason'] = 'Holidays excluded'
            leave_request['original_days'] = original_days

        return leave_request

    @staticmethod
    def execute_require_additional_approval(params: Dict[str, Any], leave_request: Dict[str, Any]) -> Dict[str, Any]:
        additional_approver = params.get('approver_role')
        if 'additional_approvers' not in leave_request:
            leave_request['additional_approvers'] = []

        if additional_approver not in leave_request['additional_approvers']:
            leave_request['additional_approvers'].append(additional_approver)

        return leave_request

    @staticmethod
    def execute_adjust_carry_forward(params: Dict[str, Any], leave_request: Dict[str, Any]) -> Dict[str, Any]:
        max_days = params.get('max_days', 5)
        leave_request['carry_forward_days'] = min(
            leave_request.get('carry_forward_requested', 0),
            max_days
        )
        leave_request['carry_forward_adjusted'] = True
        return leave_request

    @staticmethod
    def execute_expire_balance(params: Dict[str, Any], leave_request: Dict[str, Any]) -> Dict[str, Any]:
        months = params.get('months', 12)
        leave_request['balance_expiry_months'] = months
        leave_request['balance_will_expire'] = True
        return leave_request

    @staticmethod
    def execute_set_entitlement(params: Dict[str, Any], leave_request: Dict[str, Any]) -> Dict[str, Any]:
        days = params.get('days', 0)
        leave_request['entitlement_days'] = days
        return leave_request

    @staticmethod
    def execute_add_entitlement(params: Dict[str, Any], leave_request: Dict[str, Any]) -> Dict[str, Any]:
        extra_days = params.get('days', 0)
        current_entitlement = leave_request.get('entitlement_days', 0)
        leave_request['entitlement_days'] = current_entitlement + extra_days
        leave_request['bonus_days_added'] = extra_days
        return leave_request

    @staticmethod
    def execute_actions(actions: List[Dict[str, Any]], leave_request: Dict[str, Any]) -> Dict[str, Any]:
        for action in actions:
            action_type = action.get('type')
            params = action.get('params', {})

            if action_type == 'require_documentation':
                leave_request = ActionExecutor.execute_require_documentation(params, leave_request)
            elif action_type == 'require_fitness_certificate':
                leave_request = ActionExecutor.execute_require_fitness_certificate(params, leave_request)
            elif action_type == 'adjust_leave_days':
                leave_request = ActionExecutor.execute_adjust_leave_days(params, leave_request)
            elif action_type == 'require_additional_approval':
                leave_request = ActionExecutor.execute_require_additional_approval(params, leave_request)
            elif action_type == 'adjust_carry_forward':
                leave_request = ActionExecutor.execute_adjust_carry_forward(params, leave_request)
            elif action_type == 'expire_balance':
                leave_request = ActionExecutor.execute_expire_balance(params, leave_request)
            elif action_type == 'set_entitlement':
                leave_request = ActionExecutor.execute_set_entitlement(params, leave_request)
            elif action_type == 'add_entitlement':
                leave_request = ActionExecutor.execute_add_entitlement(params, leave_request)

        return leave_request


class PolicyHelper:
    @staticmethod
    def calculate_entitlement(
        policy: 'Policy',
        employee: Dict[str, Any],
        context: Dict[str, Any]
    ) -> int:
        base_entitlement = policy.entitlement.get('base_days', 10)

        full_context = {**context, **employee}

        for condition in policy.conditions:
            if RuleParser.evaluate_condition(condition, full_context):
                action = condition.get('action_if_true', {})

                if action.get('type') == 'set_entitlement':
                    base_entitlement = action.get('params', {}).get('days', base_entitlement)
                elif action.get('type') == 'add_entitlement':
                    extra_days = action.get('params', {}).get('days', 0)
                    base_entitlement += extra_days

        return base_entitlement

    @staticmethod
    def check_blackout_period(
        policy: 'Policy',
        start_date: datetime,
        end_date: datetime,
        blackout_dates: List[Tuple[datetime, datetime]]
    ) -> bool:
        for blackout_start, blackout_end in blackout_dates:
            if start_date <= blackout_end and end_date >= blackout_start:
                return True
        return False

    @staticmethod
    def calculate_encashment(
        policy: 'Policy',
        employee_balance: int,
        requested_days: int,
        salary_per_day: float
    ) -> Dict[str, Any]:
        max_encashable = policy.encashment

        if requested_days > max_encashable:
            return {
                'allowed': False,
                'reason': f'Max encashable days is {max_encashable}',
                'amount': 0
            }

        if requested_days > employee_balance:
            return {
                'allowed': False,
                'reason': 'Insufficient balance',
                'amount': 0
            }

        multiplier = policy.multiplier
        amount = requested_days * salary_per_day * multiplier

        return {
            'allowed': True,
            'amount': amount,
            'days': requested_days,
            'multiplier': multiplier,
            'calculation_base': policy.calculation_base
        }

def validate_leave_against_policy(
    policy,
    leave_request_data: Dict[str, Any],
    employee_data: Dict[str, Any],
    additional_context: Dict[str, Any] = None
) -> Dict[str, Any]:

    context = additional_context or {}

    is_eligible, eligibility_reason = RuleParser.check_policy_eligibility(policy, employee_data)

    if not is_eligible:
        return {
            'is_valid': False,
            'is_eligible': False,
            'eligibility_reason': eligibility_reason,
            'errors': [{'reason': eligibility_reason}],
            'actions': [],
            'approval_chain': []
        }

    is_valid, errors, actions = RuleParser.validate_leave_request(
        policy,
        leave_request_data,
        {**context, **employee_data}
    )

    approval_chain = RuleParser.get_approval_chain(policy, employee_data)

    return {
        'is_valid': is_valid,
        'is_eligible': True,
        'errors': errors,
        'actions': actions,
        'approval_chain': approval_chain
    }