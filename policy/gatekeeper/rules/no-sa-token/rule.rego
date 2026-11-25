package k8splatformnoserviceaccounttoken

import data.lib.workload
import future.keywords.contains
import future.keywords.if

violation contains {"msg": msg} if {
    spec := workload.pod_spec
    not spec.automountServiceAccountToken == false
    msg := sprintf("%v <%v> must set automountServiceAccountToken: false in its pod spec", [workload.obj.kind, workload.obj.metadata.name])
}