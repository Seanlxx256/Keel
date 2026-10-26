"""Repository-group reservation of public development tasks, not label approval."""


def reserve_cohort(tasks, trained_tasks, prior_assignments, repository_partitions):
    allowed={'training_review','transfer_review','quarantine'}
    by_id={}
    for task in tasks:
        key=task['instance_id']
        identity={field:task[field] for field in ('instance_id','repo','base_commit','problem_statement')}
        if key in by_id and by_id[key]!=identity:raise ValueError('Conflicting duplicate public task')
        by_id[key]=identity
    if set(repository_partitions)!={task['repo'] for task in by_id.values()}:
        raise ValueError('Explicit partition required for every repository')
    if not set(trained_tasks)<=by_id.keys():raise ValueError('Previously trained task missing')
    if not set(prior_assignments)<=by_id.keys():raise ValueError('Prior reservation task missing')
    result=[]
    for key,task in sorted(by_id.items()):
        partition=repository_partitions[task['repo']]
        if partition not in allowed:raise ValueError('Unknown repository partition')
        if key in prior_assignments and prior_assignments[key]['partition']!=partition:
            raise ValueError('Prior reservation boundary changed')
        if key in trained_tasks and partition!='training_review':raise ValueError('Trained task cannot enter evaluation')
        result.append({'instance_id':key,'repo':task['repo'],'base_commit':task['base_commit'],
                       'partition':partition,'previously_trained':key in trained_tasks,
                       'new_training_approved':False,'independent_evaluation_eligible':False,
                       'exposure':'Existing public development task; prior project exposure, not blind holdout'})
    return result
