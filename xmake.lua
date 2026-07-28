set_project("an-markov-core")
set_version("0.1.0")
set_languages("c++20")
set_warnings("all")

add_requires("ixwebsocket", {configs = {use_tls = true}})
add_requires("openssl", "simdjson", "zstd", "doctest", "cpp-httplib")

local function link_pthread()
    if is_plat("linux", "macosx") then
        add_syslinks("pthread")
    end
end

target("engine")
    set_kind("binary")
    add_files("src/main.cpp")
    add_includedirs("include")
    add_packages("ixwebsocket", "openssl", "simdjson", "cpp-httplib")
    add_defines("CPPHTTPLIB_OPENSSL_SUPPORT")
    link_pthread()

target("tests")
    set_kind("binary")
    set_default(false)
    add_files("tests/*.cpp")
    add_includedirs("include")
    add_packages("doctest", "cpp-httplib", "simdjson", "openssl", "ixwebsocket")
    add_defines("CPPHTTPLIB_OPENSSL_SUPPORT")
    link_pthread()
