"""Scoped native WALK-origin correction for the reviewed synthetic worker.

The original R5 setOrigin establishes its split and private metadata. A small
compiled helper then rebuilds reverse initial states before routing, preserving
each vertex's directional edge, distance and time association. The original
engine JAR and installed Python package remain unchanged. This experimental
context also captures native router context for the separate geometry adapter.
It supports fresh WALK searches and refuses reverse point-to-point searches.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib
import inspect
from pathlib import Path
import sys


ADAPTER_NAME = "r5-walk-origin-correction"
ADAPTER_VERSION = 1
SUPPORTED_R5PY = "1.1.7"
SOURCE_SHA256 = {
    "r5/trip_planner.py": "541bcf3ec644bb717195518699ad540d1c448330539e26b1f36cd850ff7674a7",
}
JAR_SHA256 = "d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7"
JAR_SIZE = 64_437_972
JAVA_SOURCE = Path(__file__).resolve().parent / "routing_native/HomeReachStreetOrigins.java"
JAVA_SOURCE_SHA256 = "f35f65457ba7dfeb976c50d874ffcbf0be4b4187f8bc55e88e62f31a72a6d5f5"
HELPER_CLASS = "homereach.routing.HomeReachStreetOrigins"
_ACTIVE_CONTEXTS = None


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _verified_runtime(r5py):
    if getattr(r5py, "__version__", None) != SUPPORTED_R5PY:
        raise RuntimeError("Street-origin correction requires r5py 1.1.7.")
    jobs = r5py.DetailedItineraries.NUM_THREADS
    if type(jobs) is not int or jobs != 1:
        raise RuntimeError("Street-origin correction requires one Python routing job.")
    package = Path(r5py.__file__).resolve().parent
    hashes = {}
    for relative, expected in SOURCE_SHA256.items():
        actual = hashlib.sha256((package / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Street-origin correction source mismatch: {relative}.")
        hashes[relative] = actual
    planner = importlib.import_module("r5py.r5.trip_planner")
    path = package / "r5/trip_planner.py"
    if Path(planner.__file__).resolve() != path or planner.com is not sys.modules.get("com"):
        raise RuntimeError("Street-origin correction found an unexpected planner/module namespace.")
    for name, attribute in (("direct_paths", "fget"), ("_transit_access_paths", "func"),
                            ("_transit_egress_paths", "func")):
        method = getattr(getattr(planner.TripPlanner, name), attribute, None)
        if (not inspect.isfunction(method) or method.__module__ != planner.__name__
                or method.__qualname__ != f"TripPlanner.{name}"
                or hasattr(method, "__wrapped__")
                or Path(method.__code__.co_filename).resolve() != path):
            raise RuntimeError("Street-origin correction found an already modified planner.")
    return planner, hashes


def _compile_helper(work: Path, jar: Path):
    """Compile/load the fixed helper using the already running Java 21 compiler."""
    import jpype

    if not jpype.isJVMStarted():
        raise RuntimeError("Street-origin correction requires the reviewed running JVM.")
    if jar.stat().st_size != JAR_SIZE or _sha256(jar) != JAR_SHA256:
        raise RuntimeError("Street-origin correction engine fingerprint mismatch.")
    source = JAVA_SOURCE.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(source).hexdigest() != JAVA_SOURCE_SHA256:
        raise RuntimeError("Street-origin correction helper source mismatch.")
    system = jpype.JClass("java.lang.System")
    if str(system.getProperty("java.specification.version")) != "21":
        raise RuntimeError("Street-origin correction requires the reviewed Java 21 compiler.")
    native = jpype.JClass("com.conveyal.r5.streets.StreetRouter")
    paths = jpype.JClass("java.nio.file.Paths")
    loaded_jar = Path(str(paths.get(native.class_.getProtectionDomain().getCodeSource().getLocation().toURI()))).resolve()
    if loaded_jar != jar.resolve():
        raise RuntimeError("Street-origin correction found a different loaded engine.")
    compiler = jpype.JClass("javax.tools.ToolProvider").getSystemJavaCompiler()
    if compiler is None:
        raise RuntimeError("This Java runtime does not contain the required compiler module.")
    directory = work.resolve() / "walking-origin-helper"
    directory.mkdir()
    source_path = directory / JAVA_SOURCE.name
    source_path.write_bytes(source)
    classes = directory / "classes"
    classes.mkdir()
    output = jpype.JClass("java.io.ByteArrayOutputStream")()
    # Some Java 21 runtime bundles retain the compiler but omit ct.sym, which
    # --release needs. Compile against this already verified Java 21 runtime.
    result = compiler.run(None, output, output, "-classpath", str(jar.resolve()),
                          "-d", str(classes), "-source", "21", "-target", "21", str(source_path))
    if result != 0:
        raise RuntimeError("Street-origin helper compilation failed: " + str(output.toString("UTF-8"))[-4000:])
    class_file = classes / "homereach/routing/HomeReachStreetOrigins.class"
    if not class_file.is_file():
        raise RuntimeError("Street-origin compiler did not produce the expected class.")
    # An explicit loader has a verifiable CodeSource URL. JPype's dynamic
    # addClassPath loader may report no location, which is insufficient here.
    url = jpype.JClass("java.io.File")(str(classes)).toURI().toURL()
    urls = jpype.JArray(jpype.JClass("java.net.URL"))([url])
    loader = jpype.JClass("java.net.URLClassLoader")(urls, native.class_.getClassLoader())
    try:
        helper = jpype.JClass(HELPER_CLASS, loader=loader)
        location = helper.class_.getProtectionDomain().getCodeSource().getLocation()
        loaded_directory = Path(str(paths.get(location.toURI()))).resolve()
        if loaded_directory != classes:
            raise RuntimeError("Street-origin correction found a previously loaded helper.")
        return helper, {"java_source_sha256": JAVA_SOURCE_SHA256,
                        "class_sha256": _sha256(class_file),
                        "compiler_java_version": str(system.getProperty("java.version")),
                        "compiled_in_temporary_workspace": True, "original_jar_sha256": JAR_SHA256}, loader
    except BaseException:
        loader.close()
        raise


def context_for_state(state):
    """Return the native route context captured before geometry construction."""
    if _ACTIVE_CONTEXTS is None or state not in _ACTIVE_CONTEXTS:
        raise RuntimeError("No reviewed native router context exists for this state.")
    return dict(_ACTIVE_CONTEXTS[state])


class _NamespaceOverride:
    def __init__(self, original, name, replacement):
        self._original, self._name, self._replacement = original, name, replacement

    def __getattr__(self, name):
        return self._replacement if name == self._name else getattr(self._original, name)


class _RouterProxy:
    def __init__(self, native, helper, contexts, audit):
        self._native, self._helper = native, helper
        self._contexts, self._audit = contexts, audit
        self._origin = None
        self._destination = None
        self._routed = False

    def __getattr__(self, name):
        return getattr(self._native, name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._native, name, value)

    def _require_walk(self):
        if str(self._native.streetMode) != "WALK":
            raise RuntimeError("Experimental street correction supports WALK only.")

    def setOrigin(self, lat, lon):
        self._require_walk()
        if self._origin is not None or self._routed:
            raise RuntimeError("Experimental street correction requires a fresh router.")
        if not self._native.setOrigin(lat, lon):
            raise RuntimeError("No native walking edge was found for this origin.")
        self._origin = (float(lon), float(lat))
        changed = int(self._helper.repairReverseOrigin(self._native))
        self._audit["origins_initialized"] += 1
        self._audit["reverse_states_rebuilt"] += changed
        return True

    def setDestination(self, lat, lon):
        self._require_walk()
        if self._native.profileRequest.reverseSearch:
            raise RuntimeError("Reverse point-to-point search is outside this correction's supported scope.")
        if self._origin is None or self._destination is not None or self._routed:
            raise RuntimeError("Destination must be set once after a fresh origin.")
        result = self._native.setDestination(lat, lon)
        self._destination = (float(lon), float(lat))
        return result

    def route(self):
        self._require_walk()
        if self._origin is None or self._routed:
            raise RuntimeError("Experimental street correction requires one search per router.")
        self._routed = True
        return self._native.route()

    def _register(self, state):
        if state is not None:
            if not self._routed:
                raise RuntimeError("Cannot build geometry from an unsearched router.")
            self._contexts[state] = {"router": self._native, "origin_lon_lat": self._origin,
                                     "destination_lon_lat": self._destination,
                                     "reverse": bool(self._native.profileRequest.reverseSearch)}
            self._audit["states_registered"] += 1
        return state

    def getState(self, split):
        if self._destination is None:
            raise RuntimeError("Point state requires the reviewed point destination.")
        return self._register(self._native.getState(split))

    def getStateAtVertex(self, vertex):
        return self._register(self._native.getStateAtVertex(vertex))


@contextmanager
def correct_street_origins(r5py, work: Path, jar: Path):
    """Temporarily replace this planner's router factory; restore it on exit."""
    global _ACTIVE_CONTEXTS
    if _ACTIVE_CONTEXTS is not None:
        raise RuntimeError("Street-origin correction is already active.")
    planner, hashes = _verified_runtime(r5py)
    helper, compilation, loader = _compile_helper(Path(work), Path(jar))
    original = planner.com
    original_factory = original.conveyal.r5.streets.StreetRouter
    contexts = {}
    audit = {"name": ADAPTER_NAME, "version": ADAPTER_VERSION, "r5py": SUPPORTED_R5PY,
             "source_sha256": hashes, "helper": compilation, "applied": False, "restored": False,
             "routers_created": 0, "origins_initialized": 0, "reverse_states_rebuilt": 0,
             "states_registered": 0, "helper_loader_closed": False,
             "scope": "fresh WALK searches; reverse point-to-point refused"}

    def factory(street_layer):
        audit["routers_created"] += 1
        return _RouterProxy(original_factory(street_layer), helper, contexts, audit)

    streets = _NamespaceOverride(original.conveyal.r5.streets, "StreetRouter", factory)
    r5 = _NamespaceOverride(original.conveyal.r5, "streets", streets)
    conveyal = _NamespaceOverride(original.conveyal, "r5", r5)
    replacement = _NamespaceOverride(original, "conveyal", conveyal)
    planner.com = replacement
    _ACTIVE_CONTEXTS = contexts
    audit["applied"] = True
    try:
        yield audit
    finally:
        current = planner.com
        planner.com = original
        _ACTIVE_CONTEXTS = None
        contexts.clear()
        audit["restored"] = planner.com is original
        loader.close()
        audit["helper_loader_closed"] = True
        if current is not replacement:
            raise RuntimeError("Street-origin namespace changed during its scope.")
