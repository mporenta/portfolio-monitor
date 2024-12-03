import asyncio
import subprocess
import sys
import os
from pathlib import Path

async def run_script(script_name):
    """Run a Python script as a subprocess"""
    script_path = Path(__file__).parent / script_name
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    # Handle output
    async def handle_output(stream, prefix):
        while True:
            line = await stream.readline()
            if not line:
                break
            print(f"{prefix}: {line.decode().strip()}")
            
    await asyncio.gather(
        handle_output(process.stdout, script_name),
        handle_output(process.stderr, f"{script_name} (err)")
    )
    
    return await process.wait()

async def main():
    try:
        # Run both scripts concurrently
        await asyncio.gather(
            run_script('pnl_monitor.py'),
            run_script('db.py')
        )
    except Exception as e:
        print(f"Error running scripts: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Ensure PYTHONPATH includes the current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    python_path = os.environ.get('PYTHONPATH', '')
    os.environ['PYTHONPATH'] = f"{current_dir}:{python_path}"
    
    # Run the async main function
    asyncio.run(main())