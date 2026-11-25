package k8splatformcontainerresources

import data.lib.workload
import future.keywords.contains
import future.keywords.if
import future.keywords.in

required := [["requests", "cpu"], ["requests", "memory"], ["limits", "memory"]]

violation contains {"msg": msg} if {
    some c in workload.containers
    some path in required
    object.get(c, array.concat(["resources"], path), "") == ""
    msg := sprintf("container <%v> needs resources.%v.%v", [c.name, path[0], path[1]])
}