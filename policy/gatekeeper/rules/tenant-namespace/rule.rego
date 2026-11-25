package k8splatformtenantnamespace

import future.keywords.contains
import future.keywords.if
import future.keywords.in

required_labels := {"platform.lab/tenant", "platform.lab/owner"}

psa_modes := {"enforce", "warn", "audit"}

ns := input.review.object

labels := object.get(ns.metadata, "labels", {})

violation contains {"msg": msg} if {
    not exempt(ns.metadata.name)
    some label in required_labels
    object.get(labels, label, "") == ""
    msg := sprintf("namespace <%v> needs the label <%v>", [ns.metadata.name, label])
}

violation contains {"msg": msg} if {
    not exempt(ns.metadata.name)
    some mode in psa_modes
    key := sprintf("pod-security.kubernetes.io/%v", [mode])
    object.get(labels, key, "") != "restricted"
    msg := sprintf("namespace <%v> needs <%v: restricted>", [ns.metadata.name, key])
}

exempt(name) if name in input.parameters.platformNamespaces