import asyncio
import os
from app.storage.json_storage import JSONStorage
from app.services.user_service import UserService
from app.services.task_service import TaskService


async def test_flow():
    test_storage_file = "test_data.json"
    if os.path.exists(test_storage_file):
        os.remove(test_storage_file)

    storage = JSONStorage(test_storage_file)
    await storage.init()

    user_svc = UserService(storage)
    task_svc = TaskService(storage)

    # 1. Test Seed Tasks
    await task_svc.init_default_tasks_if_empty()
    tasks = await task_svc.get_user_task_list(1001)
    assert len(tasks) >= 3, f"Expected >=3 tasks, got {len(tasks)}"
    print("✅ Default tasks initialized successfully.")

    # 2. Test User Registration & Referral
    # Referrer
    user1, is_new1 = await user_svc.get_or_create_user(1001, "user_one", "User 1")
    assert is_new1 is True
    assert user1["balance"] == 0

    # Referee with referrer=1001
    user2, is_new2 = await user_svc.get_or_create_user(1002, "user_two", "User 2", referrer_id=1001)
    assert is_new2 is True
    assert user2["balance"] == 25, f"Referee bonus mismatch: {user2['balance']}"
    
    updated_user1 = await user_svc.get_user(1001)
    assert updated_user1["balance"] == 100, f"Referrer bonus mismatch: {updated_user1['balance']}"
    print("✅ Referral & registration bonus logic verified.")

    # 3. Test Daily Bonus
    success, msg, coins = await user_svc.claim_daily_bonus(1001)
    assert success is True
    assert coins == 50
    # Second claim should fail within 24h
    success2, msg2, coins2 = await user_svc.claim_daily_bonus(1001)
    assert success2 is False
    print("✅ Daily bonus cooldown logic verified.")

    # 4. Test Task Completion & Reward
    first_task = tasks[0]
    task_id = first_task["task_id"]
    t_success, t_msg, reward = await task_svc.complete_task(1001, task_id)
    assert t_success is True
    assert reward == first_task["reward"]
    
    # Repeat completion should be blocked
    t_success2, t_msg2, reward2 = await task_svc.complete_task(1001, task_id)
    assert t_success2 is False
    print("✅ Task completion and anti-duplicate claim logic verified.")

    # Cleanup
    if os.path.exists(test_storage_file):
        os.remove(test_storage_file)

    print("🎉 All core tests passed flawlessly!")


if __name__ == "__main__":
    asyncio.run(test_flow())
