import glob, re

for f in glob.glob('cogs/*.py'):
    with open(f, 'r', encoding='utf-8') as file:
        c = file.read()
    
    lines = c.split('\n')
    new_lines = []
    for line in lines:
        if 'desc = ' in line or 'description=' in line or 'view = self._create_styled_container' in line or 'formatted_lines = ' in line or 'content +=' in line or 'f"> ' in line or '"> ' in line:
            # We want to remove `> ` and `**` from the descriptions
            
            # Special case for verification
            if 'formatted_lines = [f"> **{line.strip()}**"' in line:
                line = line.replace('"> **{line.strip()}**"', '"{line.strip()}"')
                
            # For typical descriptions
            # Replace f"> **Something**" -> f"Something"
            line = re.sub(r'f"> \*\*(.*?)\*\*"', r'f"\1"', line)
            line = re.sub(r'"> \*\*(.*?)\*\*"', r'"\1"', line)
            
            # Replace > **Something** -> Something
            line = line.replace('"> **', '"')
            line = line.replace('f"> **', 'f"')
            
            # If the line ends with **" or **\n" and we replaced the front, we also want to remove it.
            # Actually, let's just manually replace the known strings in economy-underwork.py and logging.py
            line = line.replace('f"**The treasury is closed.', 'f"The treasury is closed.')
            line = line.replace('{(rem%3600)//60}m.**"', '{(rem%3600)//60}m."')
            line = line.replace('f"**Wait {rem//60}m', 'f"Wait {rem//60}m')
            line = line.replace('shift.**"', 'shift."')
            line = line.replace('f"**Worked as a', 'f"Worked as a')
            line = line.replace('f"**Your stream was', 'f"Your stream was')
            line = line.replace('f"**The forest is', 'f"The forest is')
            line = line.replace('f"**Sold your', 'f"Sold your')
            line = line.replace('f"**Found high', 'f"Found high')
            line = line.replace('f"**Authorities intercepted', 'f"Authorities intercepted')
            line = line.replace('f"**The hustle was', 'f"The hustle was')
            line = line.replace('"> **Self-robbery is prohibited.**"', '"Self-robbery is prohibited."')
            line = line.replace('f"**Target wallet', 'f"Target wallet')
            line = line.replace('f"**Heist blown!', 'f"Heist blown!')
            line = line.replace('f"**Successful heist!', 'f"Successful heist!')
            line = line.replace('"> **Numeric input or \'all\' is required.**"', '"Numeric input or \'all\' is required."')
            line = line.replace('"> **You do not have enough liquid funds to deposit.**"', '"You do not have enough liquid funds to deposit."')
            line = line.replace('f"**Stored {amt:,}', 'f"Stored {amt:,}')
            line = line.replace('"> **You do not have enough vault balance to withdraw.**"', '"You do not have enough vault balance to withdraw."')
            line = line.replace('f"**Released {amt:,}', 'f"Released {amt:,}')
            line = line.replace('"> **You cannot transfer currency to yourself.**"', '"You cannot transfer currency to yourself."')
            line = line.replace('"> **You cannot transfer currency to bots.**"', '"You cannot transfer currency to bots."')
            line = line.replace('"> **Amount must be greater than 0.**"', '"Amount must be greater than 0."')
            line = line.replace('f"**You do not have enough', 'f"You do not have enough')
            line = line.replace('f"**Transferred {amount:,}', 'f"Transferred {amount:,}')
            line = line.replace('f"**Minimum bet is', 'f"Minimum bet is')
            line = line.replace('"> **Wallet balance too low for this bet.**"', '"Wallet balance too low for this bet."')
            line = line.replace('"> **Changes applied!**"', '"Changes applied!"')
            line = line.replace('f"**{str(error)}**"', 'f"{str(error)}"')
            line = line.replace('f"**[ {r[0]} |', 'f"[ {r[0]} |')
            line = line.replace('f"**{msg}**"', 'f"{msg}"')
            line = line.replace('{cfg[\'currency_symbol\']}.**"', '{cfg[\'currency_symbol\']}."')
            line = line.replace('{cfg[\'currency_symbol\']}!**"', '{cfg[\'currency_symbol\']}!"')
            line = line.replace('fees.**"', 'fees."')
            line = line.replace('{cfg[\'currency_name\']}.**"', '{cfg[\'currency_name\']}."')
            line = line.replace('again.**"', 'again."')
            line = line.replace('s.**"', 's."')
            line = line.replace('down.**"', 'down."')
            line = line.replace('attempt.**"', 'attempt."')
            line = line.replace('required).**"', 'required)."')
            line = line.replace('system.**"', 'system."')
            line = line.replace('wallet.**"', 'wallet."')
            
            # Remove > from multiline strings
            line = line.replace('"> **', '"**')
            line = line.replace('f"> **', 'f"**')
            line = line.replace('f"> ', 'f"')
            line = line.replace('"> ', '"')

        new_lines.append(line)
        
    c = '\n'.join(new_lines)
    with open(f, 'w', encoding='utf-8') as file:
        file.write(c)

print("Replacement complete.")
