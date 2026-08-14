# Modelo conceitual de dados

## Entidades mínimas
### MetricDefinition
- id
- name
- objective
- formula
- source
- grain
- owner
- target
- warning_threshold
- critical_threshold
- materiality_rule
- update_frequency
- version

### Alert
- id
- metric_id
- detected_at
- period
- current_value
- reference_value
- absolute_delta
- percentage_delta
- materiality
- severity
- source_quality
- status

### Diagnosis
- id
- alert_id
- facts[]
- calculations[]
- concentration[]
- hypotheses[]
- probable_cause
- confidence
- missing_data[]
- consequence_no_action
- created_at
- agent_versions[]

### Hypothesis
- id
- statement
- favorable_evidence[]
- contrary_evidence[]
- missing_evidence[]
- confidence
- status

### Recommendation
- id
- diagnosis_id
- type: containment | structural | optimization
- action
- expected_impact
- effort
- risk
- time_to_value
- reversibility
- dependencies[]
- owner_role
- deadline
- success_kpi
- success_target

### Decision
- id
- recommendation_id
- decision: approved | rejected | request_more_evidence
- human_owner
- timestamp
- rationale

### ActionExecution
- id
- decision_id
- owner
- started_at
- due_at
- completed_at
- evidence[]
- actual_impact
- outcome
- recurrence

### OrganizationalLearning
- pattern
- intervention
- predicted_impact
- actual_impact
- conditions
- lesson
- confidence
