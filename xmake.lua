set_project("an-markov-core")
set_version("0.1.0")
set_languages("c++20")
set_warnings("all")

local function link_pthread()
    if is_plat("linux", "macosx") then
        add_syslinks("pthread")
    end
end

-- Engine deps (Binance WS/REST) added when wiring live I/O.
target("engine")
    set_kind("binary")
    add_files("src/main.cpp")
    add_includedirs("include")
    link_pthread()

-- doctest vendored at third_party/doctest/doctest.h
target("tests")
    set_kind("binary")
    set_default(false)
    add_files("tests/*.cpp")
    add_includedirs("include", "third_party")
    link_pthread()
