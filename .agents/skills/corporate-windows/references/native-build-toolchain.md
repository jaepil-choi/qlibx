# Native build and missing-wheel diagnosis

1. Capture the package, version, Python version, platform tag, and first build-system error.
2. Determine whether resolution failed because of `Requires-Python`, a missing compatible wheel, a
   missing source distribution, or an actual compiler failure.
3. Check whether uv fell back from a wheel to an sdist build.
4. Identify the build backend and required toolchain: MSVC/Windows SDK, Rust/Cargo, CMake/Ninja,
   Fortran, or another native dependency.
5. Check upstream support and newer compatible releases before installing a compiler or patching
   metadata.
6. Do not silently downgrade Python, disable build isolation, or force an incompatible wheel.
7. If a temporary metadata override is proposed, label it unverified and require an independent
   install/import/smoke test.
8. Record compatibility by layer: metadata, resolution, install, import, smoke, tests, and build.

A toolchain installation is a machine-level change and requires explicit authorization. A package
that imports successfully despite conservative upstream metadata is evidence of runtime behavior,
not proof of upstream-supported compatibility.
