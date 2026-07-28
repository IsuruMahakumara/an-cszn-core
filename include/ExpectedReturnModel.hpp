#pragma once

#include "Types.hpp"

#include <limits>
#include <vector>

namespace AlphaNode {

struct Friction {
    double taker_fee{};
    double slippage{};
    double safety_margin{};

    double hurdle() const { return taker_fee + slippage + safety_margin; }
};

struct EdgeResult {
    double expected_return{std::numeric_limits<double>::quiet_NaN()};
    Decision decision{Decision::Hold};
    Side side{Side::None};
    Status status{Status::Invalid};
};

// TDD stub — implement until edge_gate_test.cpp is green.
class ExpectedReturnModel {
public:
    explicit ExpectedReturnModel(Friction friction) : friction_(friction) {}

    // f_k(x) supplied as length-K vector for the current bar.
    EdgeResult evaluate(const std::vector<double>& P,
                        const std::vector<double>& f_k,
                        Status upstream = Status::Ok) {
        (void)P;
        (void)f_k;
        (void)upstream;
        return {};
    }

    const Friction& friction() const { return friction_; }

private:
    Friction friction_;
};

}  // namespace AlphaNode
