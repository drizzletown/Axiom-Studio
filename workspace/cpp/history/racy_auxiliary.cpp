// Deliberate data race on auxiliary state, while visible ledger behavior stays locked.
// This demonstrates why history linearizability cannot establish race freedom.
#include <mutex>
static std::mutex shared_mutex;
static int left_value=0, right_value=0;
static int auxiliary_counter=0;  // intentionally unprotected
extern "C" void axiom_reset(int left,int right) {
    std::lock_guard<std::mutex> lk(shared_mutex);
    left_value=left;right_value=right;auxiliary_counter=0;
}
extern "C" int axiom_aux_counter() { return auxiliary_counter; }
extern "C" int axiom_call(int opcode,int desired) {
    int result=0;
    {
      std::lock_guard<std::mutex> lk(shared_mutex);
      if(opcode==0) { left_value=desired;right_value=desired;result=1; }
      else if(opcode==1) result=left_value;
      else if(opcode==2) result=right_value;
      else result=-1;
    }
    if(opcode==0) { // two writers can race, despite correct visible state
        std::this_thread::yield();
        auxiliary_counter=auxiliary_counter+1;
    }
    return result;
}
extern "C" void axiom_snapshot(int* left,int* right) {
    std::lock_guard<std::mutex> lk(shared_mutex);
    *left=left_value;*right=right_value;
}
