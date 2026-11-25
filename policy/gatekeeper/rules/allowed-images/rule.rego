package k8splatformallowedimages

import data.lib.workload
import future.keywords.contains
import future.keywords.if
import future.keywords.in

violation contains {"msg": msg} if {
    some c in workload.all_containers
    not allowed_registry(c.image)
    msg := sprintf("container <%v> image <%v> is not from an allowed registry: %v", [c.name, c.image, input.parameters.registries])
}

violation contains {"msg": msg} if {
    some c in workload.all_containers
    not pinned(c.image)
    msg := sprintf("container <%v> image <%v> names no version: use a digest or a tag other than latest", [c.name, c.image])
}

allowed_registry(image) if {
    some prefix in input.parameters.registries
    startswith(image, prefix)
}

pinned(image) if contains(last_segment(image), "@sha256:")

pinned(image) if {
    tag := image_tag(image)
    tag != ""
    tag != "latest"
}

# The part after the last "/": a registry port ("localhost:5000/app") is never read as a tag.
last_segment(image) := s if {
    parts := split(image, "/")
    s := parts[count(parts) - 1]
}

image_tag(image) := tag if {
    segment := last_segment(image)
    not contains(segment, "@")
    parts := split(segment, ":")
    count(parts) == 2
    tag := parts[1]
}