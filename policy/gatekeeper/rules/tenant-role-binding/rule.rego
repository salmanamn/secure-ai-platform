package k8splatformtenantrolebinding

import future.keywords.contains
import future.keywords.if
import future.keywords.in

rb := input.review.object

namespace := rb.metadata.namespace

violation contains {"msg": msg} if {
    not allowed_role(rb.roleRef)
    msg := sprintf("RoleBinding <%v>: roleRef %v %v is not one of the ClusterRoles %v", [rb.metadata.name, rb.roleRef.kind, rb.roleRef.name, input.parameters.allowedClusterRoles])
}

violation contains {"msg": msg} if {
    some subject in object.get(rb, "subjects", [])
    not allowed_subject(subject)
    msg := sprintf("RoleBinding <%v>: subject %v %v is not a group tenant:%v:... or a service account of <%v>", [rb.metadata.name, subject.kind, subject.name, namespace, namespace])
}

allowed_role(ref) if {
    ref.kind == "ClusterRole"
    ref.name in input.parameters.allowedClusterRoles
}

allowed_subject(subject) if {
    subject.kind == "Group"
    startswith(subject.name, sprintf("tenant:%v:", [namespace]))
}

allowed_subject(subject) if {
    subject.kind == "ServiceAccount"
    subject.namespace == namespace
}