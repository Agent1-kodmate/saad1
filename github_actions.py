import os
import logging
import sys
from datetime import datetime
from dotenv import load_dotenv
from github import Github
from git import Repo, InvalidGitRepositoryError, GitCommandError
import requests
import subprocess
from groq import Groq

# Load .env vars
load_dotenv()
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
github_client = Github(GITHUB_TOKEN)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY)

API_URL = "https://api.github.com"
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}


def sanitize_repo_name(repo_name: str) -> str:
    return repo_name.strip().replace(" ", "-")



def create_github_repo(repo_name):
    try:
        if not repo_name or repo_name.lower() == "not specified":
            repo_name = "testrepo_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        repo_name = sanitize_repo_name(repo_name)

        user = github_client.get_user()
        existing = [r.name for r in user.get_repos()]
        if repo_name in existing:
            repo = user.get_repo(repo_name)
            print(f"Repository already exists: {repo.html_url}")
            return

        repo = user.create_repo(repo_name)
        try:
            repo.create_file(
                "README.md",
                "Initial commit",
                f"# {repo_name}\nRepository created by GitHub Automation Bot."
            )
        except Exception as e:
            print(f"Warning: could not create README.md: {e}")

        print(f"Created repository: {repo.html_url}")
        return repo.html_url
    except Exception as e:
        print(f"Error creating repository: {e}")


def clone_repo(repo_name: str):
    try:
        safe = sanitize_repo_name(repo_name)
        repo_url = f"https://github.com/{GITHUB_USERNAME}/{safe}.git"
        local_dir = os.path.join(".", safe)

        if os.path.exists(local_dir):
            print(f"Already cloned at {local_dir}")
            return {"success": True, "message": "Already cloned", "local_path": local_dir}

        Repo.clone_from(repo_url, local_dir)
        print(f"Cloned to {local_dir}")
        return {"success": True, "message": "Cloned successfully", "local_path": local_dir}

    except Exception as e:
        print(f"Error cloning repository: {e}")
        return {"success": False, "message": str(e), "local_path": None}


def create_branch(repo_name: str, branch_name: str):
    try:
        safe = sanitize_repo_name(repo_name)
        local_dir = os.path.join(".", safe)

        if not os.path.exists(local_dir):
            print(f"Local repo not found, cloning first...")
            clone_result = clone_repo(repo_name)
            if not clone_result.get("success"):
                return {"success": False, "message": "Failed to clone repo", "branch": None}

        repo = Repo(local_dir)

        if not repo.heads:
            # Ensure at least one commit exists
            dummy = os.path.join(local_dir, ".init")
            with open(dummy, "w") as f:
                f.write("init")
            repo.git.add(all=True)
            repo.index.commit("initial commit")
            repo.git.checkout("-b", "init")

        repo.git.reset("--hard", "HEAD")
        try:
            repo.git.branch("-D", branch_name)
        except GitCommandError:
            pass  # Branch might not exist, which is fine
        repo.git.checkout("-B", branch_name)
        print(f"Branch '{branch_name}' created in {local_dir}")
        return {"success": True, "message": f"Branch '{branch_name}' created", "branch": branch_name, "path": local_dir}

    except Exception as e:
        print(f"Error creating branch: {e}")
        return {"success": False, "message": str(e), "branch": None}



def commit_changes(repo_name, file_path, commit_message, file_content="Sample content"):
    try:
        safe = sanitize_repo_name(repo_name)
        local_dir = f"./{safe}"
        os.makedirs(local_dir, exist_ok=True)
        full = os.path.join(local_dir, file_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        
        if file_content is None:
            with open(file_path, "r") as src:
                file_content = src.read()

        with open(full, "w") as f:
            f.write(file_content)

        try:
            repo = Repo(local_dir)
        except InvalidGitRepositoryError:
            print("Initializing new Git repository...")
            repo = Repo.init(local_dir)
            repo.create_remote("origin", f"https://github.com/{GITHUB_USERNAME}/{safe}.git")

        repo.git.add(A=True)

        try:
            commit = repo.index.commit(commit_message)
            commit_hash = commit.hexsha
            print(f"Committed '{file_path}': {commit_hash}")
            return {
                "success": True,
                "message": f"Committed '{file_path}'",
                "commit_hash": commit_hash,
                "repo_path": local_dir
            }
        except Exception as e:
            print(f"No commit made: {e}")
            return {
                "success": False,
                "message": f"No commit made: {e}",
                "commit_hash": None,
                "repo_path": local_dir
            }

    except Exception as e:
        print(f"Error committing changes: {e}")
        return {
            "success": False,
            "message": str(e),
            "commit_hash": None,
            "repo_path": None
        }


def push_changes(repo_name):
    try:
        safe = sanitize_repo_name(repo_name)
        local_dir = f"./{safe}"
        if not os.path.exists(local_dir):
            print("Local repo not found, cloning first...")
            clone_repo(repo_name)
        repo = Repo(local_dir)

        try:
            branch = repo.active_branch
        except Exception as e:
            print(f"No active branch (detached HEAD): {e}")
            return

        if not any(r.name == "origin" for r in repo.remotes):
            repo.create_remote("origin", f"https://github.com/{GITHUB_USERNAME}/{safe}.git")
        origin = repo.remote("origin")

        if branch.tracking_branch() is None:
            repo.git.push("--set-upstream", "origin", branch.name)
        else:
            origin.push()
        print(f"Pushed branch '{branch.name}' to origin")
    except Exception as e:
        print(f"Error pushing changes: {e}")


def read_file(repo_name: str, file_path: str):
    try:
        local_dir = os.path.join(".", repo_name)
        if not os.path.exists(local_dir):
            print("Local repo not found, cloning first...")
            clone_repo(repo_name)
        full = os.path.join(local_dir, file_path)
        if not os.path.exists(full):
            print(f"File not found: {file_path}")
            return
        with open(full) as f:
            content = f.read()
        print(f"Contents of '{file_path}':\n{content}")
    except Exception as e:
        print(f"Error reading file: {e}")


def list_repos():
    try:
        user = github_client.get_user()
        repos = user.get_repos()
        print("Your repositories:")
        for r in repos:
            print(f" - {r.name}: {r.html_url}")
    except Exception as e:
        print(f"Error listing repositories: {e}")


def list_branches(repo_name: str):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        branches = repo.get_branches()
        print(f"Branches in '{repo_name}':")
        for b in branches:
            print(f" - {b.name}")
    except Exception as e:
        print(f"Error listing branches: {e}")


def analyze_repo_structure(repo_name: str):
    try:
        local_dir = os.path.join(".", repo_name)
        if not os.path.exists(local_dir):
            print("Local repo not found, cloning first...")
            clone_repo(repo_name)

        print(f"Structure of '{repo_name}':")
        for root, dirs, files in os.walk(local_dir):
            if ".git" in root:
                continue
            level = root.replace(local_dir, "").count(os.sep)
            indent = " " * 4 * level
            if level > 0:
                print(f"{indent}{os.path.basename(root)}/")
            for fname in files:
                if not fname.startswith("."):
                    print(f"{indent}    {fname}")
    except Exception as e:
        print(f"Error analyzing repository structure: {e}")


def list_issues(repo_name: str):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        issues = repo.get_issues(state="open")
        print(f"Open issues in '{repo_name}':")
        for i in issues:
            print(f" - #{i.number} {i.title}: {i.html_url}")
    except Exception as e:
        print(f"Error listing issues: {e}")


def create_github_issue(repo_name: str, title: str, body: str = "", labels=None):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        issue = repo.create_issue(title=title, body=body, labels=labels or [])
        print(f"Issue created: {issue.html_url}")
    except Exception as e:
        print(f"Error creating issue: {e}")


def auto_label_issue(repo_name, issue_number, labels):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        issue = repo.get_issue(number=issue_number)
        issue.set_labels(*labels)
        print(f"Added labels {labels} to issue #{issue_number}")
    except Exception as e:
        print(f"Error labeling issue: {e}")


def auto_merge_pr(repo_name, pr_number, merge_msg="Auto-merged by bot"):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        if not pr.mergeable:
            print(f"PR #{pr_number} is not mergeable")
            return
        result = pr.merge(commit_message=merge_msg)
        if result.merged:
            print(f"PR #{pr_number} merged successfully")
        else:
            print(f"Failed to merge PR #{pr_number}")
    except Exception as e:
        print(f"Error merging PR: {e}")


def create_release(repo_name, tag_name, release_name, body="", draft=True):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        release = repo.create_git_release(
            tag=tag_name,
            name=release_name,
            message=body,
            draft=draft,
            prerelease=False
        )
        print(f"Release '{release_name}' created: {release.html_url}")
    except Exception as e:
        print(f"Error creating release: {e}")


def get_commit_activity(repo_name):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        commits = list(repo.get_commits())[:5]
        print(f"Last 5 commits in '{repo_name}':")
        for c in commits:
            date = c.commit.author.date
            msg = c.commit.message.strip()
            sha = c.sha[:7]
            print(f" - [{date}] {msg} ({sha})")
    except Exception as e:
        print(f"Error fetching commits: {e}")


def assign_users(repo_name, issue_number, assignees):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        issue = repo.get_issue(number=issue_number)
        issue.add_to_assignees(*assignees)
        print(f"Assigned {assignees} to issue #{issue_number}")
    except Exception as e:
        print(f"Error assigning users: {e}")


def sync_branch_with_main(repo_name, branch_name):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        main = repo.get_branch("main")
        branch = repo.get_branch(branch_name)
        repo.merge(branch.name, main.commit.sha)
        print(f"Synchronized branch '{branch_name}' with main")
    except Exception as e:
        print(f"Error syncing branches: {e}")


def create_workflow(repo_name, filename="ci.yml"):
    try:
        content = """name: CI
on:
  push:
    branches: [ main ]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: echo Hello, world!
"""
        repo = github_client.get_user().get_repo(repo_name)
        repo.create_file(f".github/workflows/{filename}", "Add CI workflow", content)
        print(f"Workflow '{filename}' created in '{repo_name}'")
    except Exception as e:
        print(f"Error creating workflow: {e}")


def delete_repo(repo_name):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        repo.delete()
        print(f"Deleted repository '{repo_name}'")
    except Exception as e:
        print(f"Error deleting repository: {e}")


def rename_repository(old_name, new_name):
    try:
        repo = github_client.get_user().get_repo(old_name)
        repo.edit(name=new_name)
        print(f"Renamed repository to '{new_name}'")
    except Exception as e:
        print(f"Error renaming repository: {e}")

def generate_code(request_prompt):
    """
    Generate code from a natural language prompt using the Groq LLM.
    
    Args:
        request_prompt (str): Prompt for code generation (e.g., "Write an HTML contact form").
        
    Returns:
        str: Generated code, or an error message.
    """
    messages = [
    {
        "role": "system",
        "content": (
            "You are an expert programmer. Write clean, concise, and correct code based on the user's instructions. "
            "Your response must include only the final code — no explanations, no formatting tags, no extra words, "
            "and no quotation marks. Do not mention the programming language. Just output the code."
        )
    },
    {
        "role": "user",
        "content": request_prompt
    }
]

    try:
        response = groq_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=messages,
            temperature=0.3,
            max_completion_tokens=1024,
            tool_choice="none"
        )
        generated_code = response.choices[0].message.content.strip()
        return generated_code
    except Exception as e:
        logger.error(f"Error generating code: {e}")
        return "Sorry, I encountered an error generating the code."

def update_code(existing_code, instruction):
    """
    Modify the provided code intelligently based on a high-level natural language instruction.
    
    Args:
        existing_code (str): Current code.
        instruction (str): Instruction for modification.
        
    Returns:
        str: Updated code after modifications.
    """
    system_prompt = (
        "You are an expert programmer and code refiner."
        "Analyze the provided code and modify it according to the instruction."
        "Your response must contain only the final, updated code — no explanations, no formatting tags, no extra text, no quotation marks, and no language identifiers."
        "Ensure the code is syntactically correct and complete."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"Here is the current code:\n```python\n{existing_code}\n```\n"
            f"Modify it as per the following instruction:\n{instruction}\n"
            f"Provide only the final updated code."
        )}
    ]
    try:
        response = groq_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=messages,
            temperature=0.3,
            max_completion_tokens=2048,
            tool_choice="none"
        )
        updated_code = response.choices[0].message.content.strip()
        return updated_code
    except Exception as e:
        logger.error(f"Error in intelligent_code_modifier: {e}")
        #return f"Sorry, I encountered an error while modifying the code: {e}"

def update_existing_code(repo_name, file_path, instruction):
    """
    Modify a file from the local GitHub repo based on natural language instruction.
    
    Args:
        repo_name (str): Repository name (should already be cloned).
        file_path (str): Path to the file inside the repo.
        instruction (str): High-level natural language instruction.
        
    Returns:
        dict: Result containing success status and message.
    """
    try:
        repo_dir = f"./{sanitize_repo_name(repo_name)}"
        full_path = os.path.join(repo_dir, file_path)

        if not os.path.exists(full_path):
            print(f"File '{file_path}' does not exist in '{repo_dir}'.")
        
        with open(full_path, "r", encoding="utf-8") as f:
            existing_code = f.read()

        updated_code = update_code(existing_code, instruction)

        #with open(full_path, "w", encoding="utf-8") as f:
         #   f.write(updated_code)

        commit_changes(repo_name, file_path,"1st commit", updated_code)
        push_changes(repo_name)
    except Exception as e:
        logger.error(f"Error in update_existing_code : {e}")
        #return {"success": False, "message": f"Error: {e}"}




# ------------------ Workflow Functions ------------------

def generate_and_push_code(repo_name, filename, prompt):
    """
    Generate code using the given prompt, then write it to a file, commit, and push to GitHub.
    
    Args:
        repo_name (str): Repository name.
        filename (str): Filename to store the generated code.
        prompt (str): Natural language prompt for code generation.
        
    Returns:
        dict: Summary of generation, commit, and push process.
    """
    generated_code = generate_code(prompt)
    #logger.info("Generated code:\n" + generated_code)
    
    local_dir = f"./{sanitize_repo_name(repo_name)}"
    if not os.path.exists(local_dir):
        clone_repo(repo_name)
    
    #write_code_to_file(local_dir, filename, generated_code)
    commit_changes(repo_name, filename, "Initial commit: Generated code", generated_code)
    push_changes(repo_name)
    