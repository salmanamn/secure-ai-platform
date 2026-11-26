package k8splatformtenantnetworkpolicy

import future.keywords.contains
import future.keywords.if
import future.keywords.in

np := input.review.object

namespace := np.metadata.namespace

name_key := "kubernetes.io/metadata.name"

violation contains {"msg": msg} if {
    some rule in object.get(np.spec, "ingress", [])
    count(object.get(rule, "from", [])) == 0
    msg := sprintf("NetworkPolicy <%v>: an ingress rule without from admits every source", [np.metadata.name])
}

violation contains {"msg": msg} if {
    some rule in object.get(np.spec, "ingress", [])
    some peer in object.get(rule, "from", [])
    not same_namespace_pods(peer)
    msg := sprintf("NetworkPolicy <%v>: ingress only from pods of namespace <%v>", [np.metadata.name, namespace])
}

violation contains {"msg": msg} if {
    some rule in object.get(np.spec, "egress", [])
    count(object.get(rule, "to", [])) == 0
    msg := sprintf("NetworkPolicy <%v>: an egress rule without to reaches every destination", [np.metadata.name])
}

violation contains {"msg": msg} if {
    some rule in object.get(np.spec, "egress", [])
    some peer in object.get(rule, "to", [])
    not allowed_egress(peer)
    msg := sprintf("NetworkPolicy <%v>: egress peer %v is not this tenant's pods, an allowed namespace %v or an allowed range %v", [np.metadata.name, peer, input.parameters.egressNamespaces, tenant_cidrs])
}

tenant_cidrs := object.get(object.get(input.parameters, "egressCIDRs", {}), namespace, [])

# A peer with only a podSelector: pods of the policy's own namespace.
same_namespace_pods(peer) if {
    object.keys(peer) == {"podSelector"}
}

allowed_egress(peer) if same_namespace_pods(peer)

# A namespace named exactly (matchLabels on kubernetes.io/metadata.name, nothing else), optionally with a podSelector.
allowed_egress(peer) if {
    object.keys(peer) - {"podSelector"} == {"namespaceSelector"}
    object.keys(peer.namespaceSelector) == {"matchLabels"}
    object.keys(peer.namespaceSelector.matchLabels) == {name_key}
    peer.namespaceSelector.matchLabels[name_key] in input.parameters.egressNamespaces
}

allowed_egress(peer) if {
    object.keys(peer) == {"ipBlock"}
    peer.ipBlock.cidr in tenant_cidrs
}