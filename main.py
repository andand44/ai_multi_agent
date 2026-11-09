import asyncio
import uuid
import os
from graph import build_graph


async def main():
    app = await build_graph()

    task = (
        "Напиши полноценную браузерную логическую головоломку на HTML/JS/CSS "
        "(например, 2048, Сапер, Пятнашки или Сокобан). "
        "У игры должна быть сетка, пошаговая механика (клики или стрелки) "
        "и условие победы/поражения."
    )

    run_id = str(uuid.uuid4())[:6]
    game_folder = f"game_{run_id}"

    print(f"📥 Задача: {task}")
    print(f"📁 Игра будет сохранена в: workspace/{game_folder}\n")

    initial_state = {
        "task": task,
        "game_folder": game_folder,
        "iterations": 0,
        "plan": "",
        "feedback": "",
        "generated_code": "",
        "best_code": "",
        "test_action": "",
        "test_expected_key": "",
    }

    final_state = await app.ainvoke(initial_state)

    print("\n" + "=" * 40)
    if final_state.get("feedback") == "PASS":
        print(f"✅ Успех! Игра сохранена в: workspace/{game_folder}")
    else:
        folder_path = os.path.join("workspace", game_folder)
        failed_path = os.path.join("workspace", f"FAILED_{game_folder}")
        if os.path.exists(folder_path) and not os.path.exists(failed_path):
            os.rename(folder_path, failed_path)
            print(f"❌ Провал! Игра перемещена в: workspace/FAILED_{game_folder}")
        else:
            print("❌ Провал! Проверь логи.")


if __name__ == "__main__":
    asyncio.run(main())