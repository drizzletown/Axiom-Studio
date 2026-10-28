#include <mutex>
static std::mutex mx;
static int src=0,dst=0;
extern "C" void axiom_reset(int l,int r) {
    std::lock_guard<std::mutex> lk(mx);src=l;dst=r;
}
extern "C" int axiom_call(int op,int desired) {
    std::lock_guard<std::mutex> lk(mx);
    if(op==0) {src=desired;return 1;} // Deliberately violates mirrored state
    if(op==1) return src;
    if(op==2) return dst;
    return -1;
}
extern "C" void axiom_snapshot(int* l,int* r) {
    std::lock_guard<std::mutex> lk(mx);*l=src;*r=dst;
}
