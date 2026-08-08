cmake_minimum_required(VERSION 3.20)
project(PhoebeCleaner LANGUAGES CXX)

add_executable(PhoebeCleaner WIN32 src/main.cpp)
target_compile_features(PhoebeCleaner PRIVATE cxx_std_20)
target_compile_definitions(PhoebeCleaner PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(PhoebeCleaner PRIVATE gdiplus shell32 user32 gdi32 advapi32 winmm)

if(MINGW)
  target_link_options(PhoebeCleaner PRIVATE -municode -static -static-libgcc -static-libstdc++)
endif()

add_library(PhoebeShellExtension SHARED src/shell_extension.cpp)
target_compile_features(PhoebeShellExtension PRIVATE cxx_std_20)
target_compile_definitions(PhoebeShellExtension PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(PhoebeShellExtension PRIVATE ole32 shell32 shlwapi advapi32 user32 uuid)
set_target_properties(PhoebeShellExtension PROPERTIES PREFIX "")

if(MINGW)
  target_link_options(PhoebeShellExtension PRIVATE -static -static-libgcc -static-libstdc++)
endif()
