// Deliberately concurrency-specific bug; atomics avoid undefined data races.
// Sequential calls behave correctly, overlapping setters corrupt the mirror.
#include <atomic>
#include <chrono>
#include <thread>
static std::atomic<int> src{0},dst{0},active{0};
static std::atomic<bool> overlap_seen{false};
extern "C" void axiom_reset(int l,int r) {
    src.store(l);dst.store(r);active.store(0);overlap_seen.store(false);
}
extern "C" int axiom_call(int op,int desired) {
    if(op==0) {
        active.fetch_add(1);
        auto until=std::chrono::steady_clock::now()+std::chrono::milliseconds(100);
        while(active.load(std::memory_order_seq_cst)<2 &&
              std::chrono::steady_clock::now()<until) std::this_thread::yield();
        if(active.load(std::memory_order_seq_cst)>=2) overlap_seen.store(true);
        src.store(desired);
        dst.store(overlap_seen.load() ? 1-desired : desired);
        active.fetch_sub(1);
        return 1;
    }
    if(op==1) return src.load();
    if(op==2) return dst.load();
    return -1;
}
extern "C" void axiom_snapshot(int* l,int* r) {
    *l=src.load();*r=dst.load();
}
