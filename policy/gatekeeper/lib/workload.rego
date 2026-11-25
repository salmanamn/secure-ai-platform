package lib.workload

# The pod spec of the object under review, for every kind that makes pods. A Deployment is judged when it is applied,
# not later, when its ReplicaSet fails to create pods where nobody is looking (D4).

import future.keywords.contains
import future.keywords.if
import future.keywords.in

template_kinds := {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job"}

obj := input.review.object

pod_spec := obj.spec if obj.kind == "Pod"

pod_spec := obj.spec.template.spec if obj.kind in template_kinds

pod_spec := obj.spec.jobTemplate.spec.template.spec if obj.kind == "CronJob"

# Containers that run the workload: they can set resources.
containers contains c if {
    some c in pod_spec.containers
}

containers contains c if {
    some c in pod_spec.initContainers
}

# Every container, including the ephemeral ones `kubectl debug` adds: they run images too.
all_containers contains c if {
    some c in containers
}

all_containers contains c if {
    some c in pod_spec.ephemeralContainers
}