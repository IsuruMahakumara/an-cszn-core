#pragma once

#include "Types.hpp"

#include <string>
#include <unordered_map>

namespace AlphaNode {

struct OrderRequest {
    std::string symbol;
    Side side{Side::None};
    double qty{};
    double price{};
    FilterSpec filters{};
};

struct OrderResult {
    Status status{Status::Invalid};
    bool ok{false};
    double position{};
    std::string error;
};

// TDD stub — implement until execute_test.cpp is green.
class ExecutionRouter {
public:
    explicit ExecutionRouter(bool demo = true) : demo_(demo) {}

    OrderResult send(const OrderRequest& req) {
        (void)req;
        return {};
    }

    void set_auth_ok(bool ok) { auth_ok_ = ok; }
    void simulate_ws_drop() { connected_ = false; }
    bool connected() const { return connected_; }

    // Returns true if reconnect + REST sync restored state.
    bool recover() { return false; }

    double position(const std::string& symbol) const {
        auto it = positions_.find(symbol);
        return it == positions_.end() ? 0.0 : it->second;
    }

    bool demo() const { return demo_; }

private:
    bool demo_{true};
    bool auth_ok_{true};
    bool connected_{true};
    std::unordered_map<std::string, double> positions_;
};

}  // namespace AlphaNode
